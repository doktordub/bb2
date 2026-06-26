"""Schema parsing and cross-reference validation for backend configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.config.env_resolver import has_env_reference
from app.config.redaction import is_sensitive_key
from app.config.schemas import AgentConfig, BackendConfig, LLMProfileConfig, StoreConfig
from app.contracts.errors import ConfigurationError

_DUMMY_SECRET_VALUES = frozenset(
    {
        "dummy",
        "dummy-key",
        "test",
        "test-key",
        "example",
        "example-key",
        "changeme",
        "replace-me",
        "placeholder",
        "local-dev-only",
    }
)


def parse_backend_config(config_data: Mapping[str, Any]) -> BackendConfig:
    """Parse external config data into strict Pydantic models."""

    try:
        return BackendConfig.model_validate(dict(config_data))
    except ValidationError as exc:
        message = "; ".join(_format_validation_error(error) for error in exc.errors())
        raise ConfigurationError(f"Invalid configuration schema: {message}") from exc


def validate_literal_secrets(config_data: Mapping[str, Any]) -> None:
    """Reject non-placeholder secret literals committed directly into YAML."""

    _walk_for_literal_secrets(config_data, segments=[])


def validate_backend_config(config: BackendConfig) -> None:
    """Validate cross-references and runtime-safety rules across config sections."""

    errors: list[str] = []

    _validate_api_config(errors, config=config)

    active_usecase = config.usecases.get(config.app.active_usecase)
    if active_usecase is None:
        errors.append(
            f"Active use case '{config.app.active_usecase}' is not defined in usecases."
        )
    elif not active_usecase.enabled:
        errors.append(f"Active use case '{config.app.active_usecase}' is disabled.")

    llm_profiles = config.llm.profiles
    llm_providers = config.llm.providers
    policy_profiles = config.policy.profiles

    if config.llm.default_profile not in llm_profiles:
        errors.append(
            f"LLM default profile '{config.llm.default_profile}' is not defined."
        )

    if config.policy.default_profile not in policy_profiles:
        errors.append(
            f"Policy default profile '{config.policy.default_profile}' is not defined."
        )

    for usecase_name, usecase in config.usecases.items():
        strategy = config.strategies.get(usecase.strategy)
        if strategy is None:
            errors.append(
                f"Use case '{usecase_name}' references unknown strategy '{usecase.strategy}'."
            )
        elif not strategy.enabled:
            errors.append(
                f"Use case '{usecase_name}' references disabled strategy '{usecase.strategy}'."
            )

        default_agent = config.agents.get(usecase.default_agent)
        if default_agent is None:
            errors.append(
                f"Use case '{usecase_name}' references unknown default agent "
                f"'{usecase.default_agent}'."
            )
        elif not default_agent.enabled:
            errors.append(
                f"Use case '{usecase_name}' references disabled default agent "
                f"'{usecase.default_agent}'."
            )

        if usecase.orchestrator_llm_profile is not None and usecase.orchestrator_llm_profile not in llm_profiles:
            errors.append(
                f"Use case '{usecase_name}' references unknown orchestrator LLM profile "
                f"'{usecase.orchestrator_llm_profile}'."
            )

        if usecase.policy_profile not in policy_profiles:
            errors.append(
                f"Use case '{usecase_name}' references unknown policy profile "
                f"'{usecase.policy_profile}'."
            )

        allowed_tool_names = set(usecase.tools.allowed_tools)
        for agent_name in usecase.allowed_agents:
            agent = config.agents.get(agent_name)
            if agent is None:
                errors.append(
                    f"Use case '{usecase_name}' references unknown allowed agent '{agent_name}'."
                )
                continue
            if not agent.enabled:
                errors.append(
                    f"Use case '{usecase_name}' references disabled allowed agent '{agent_name}'."
                )
            _validate_agent_tool_subset(
                errors,
                usecase_name=usecase_name,
                usecase_tools_enabled=usecase.tools.enabled,
                allowed_tool_names=allowed_tool_names,
                agent_name=agent_name,
                agent=agent,
            )

    for strategy_name, strategy in config.strategies.items():
        if strategy.llm_profile is not None and strategy.llm_profile not in llm_profiles:
            errors.append(
                f"Strategy '{strategy_name}' references unknown LLM profile "
                f"'{strategy.llm_profile}'."
            )

    for agent_name, agent in config.agents.items():
        if agent.llm_profile is not None and agent.llm_profile not in llm_profiles:
            errors.append(
                f"Agent '{agent_name}' references unknown LLM profile '{agent.llm_profile}'."
            )

    for profile_name, profile in llm_profiles.items():
        if profile.provider not in llm_providers:
            errors.append(
                f"LLM profile '{profile_name}' references unknown provider '{profile.provider}'."
            )
        for fallback_name in profile.fallback_profiles:
            if fallback_name not in llm_profiles:
                errors.append(
                    f"LLM profile '{profile_name}' references unknown fallback profile "
                    f"'{fallback_name}'."
                )

    fallback_cycle = _find_fallback_cycle(llm_profiles)
    if fallback_cycle is not None:
        errors.append(f"LLM fallback cycle detected: {' -> '.join(fallback_cycle)}.")

    _validate_store(errors, store_name="workflow_state", store=config.persistence.workflow_state)
    _validate_store(errors, store_name="trace", store=config.persistence.trace)
    _validate_store(errors, store_name="memory", store=config.persistence.memory)

    if config.app.environment != "test" and not config.observability.redact_secrets:
        errors.append("observability.redact_secrets must remain enabled outside test environments.")

    if config.app.environment != "test" and config.health.expose_secret_values:
        errors.append("health.expose_secret_values must remain false outside test environments.")

    if errors:
        raise ConfigurationError("; ".join(errors))


def _validate_api_config(errors: list[str], *, config: BackendConfig) -> None:
    api = config.api

    if api.request_limits.max_metadata_bytes > api.request_limits.max_body_bytes:
        errors.append(
            "api.request_limits.max_metadata_bytes must be less than or equal to "
            "api.request_limits.max_body_bytes."
        )

    if api.sessions.session_id_header.lower() == api.tracing.response_trace_header.lower():
        errors.append(
            "api.sessions.session_id_header and api.tracing.response_trace_header "
            "must be different."
        )

    if api.debug_routes.enabled and not config.features.trace_enabled:
        errors.append("api.debug_routes.enabled requires features.trace_enabled to be true.")


def _validate_agent_tool_subset(
    errors: list[str],
    *,
    usecase_name: str,
    usecase_tools_enabled: bool,
    allowed_tool_names: set[str],
    agent_name: str,
    agent: AgentConfig,
) -> None:
    if not usecase_tools_enabled or not allowed_tool_names or not agent.allowed_tools:
        return

    disallowed_tools = sorted(set(agent.allowed_tools) - allowed_tool_names)
    if disallowed_tools:
        errors.append(
            f"Agent '{agent_name}' allows tools {disallowed_tools} that are not permitted "
            f"by use case '{usecase_name}'."
        )


def _validate_store(errors: list[str], *, store_name: str, store: StoreConfig) -> None:
    sqlite_config = store.sqlite
    has_legacy_path = isinstance(store.path, str) and store.path.strip() != ""
    has_sqlite_path = sqlite_config is not None and isinstance(sqlite_config.path, str) and sqlite_config.path.strip() != ""

    if store.provider == "sqlite" and not (has_legacy_path or has_sqlite_path or store_name in {"workflow_state", "trace"}):
        errors.append(f"Persistence store '{store_name}' requires a path when provider is 'sqlite'.")

    if store.provider == "memory_store":
        memory_store = store.memory_store
        legacy_database_path = store.config.get("database_path")
        has_legacy_database_path = isinstance(legacy_database_path, str) and legacy_database_path.strip() != ""
        has_memory_database_path = (
            memory_store is not None
            and isinstance(memory_store.database_path, str)
            and memory_store.database_path.strip() != ""
        )
        has_memory_config_path = (
            memory_store is not None
            and isinstance(memory_store.config_path, str)
            and memory_store.config_path.strip() != ""
        )

        if not (has_legacy_database_path or has_memory_database_path or has_memory_config_path):
            errors.append(
                f"Persistence store '{store_name}' requires memory_store.config_path, "
                f"memory_store.database_path, or config.database_path when provider is "
                f"'memory_store'."
            )

        if (
            memory_store is not None
            and memory_store.search_limit_default > memory_store.search_limit_max
        ):
            errors.append(
                "Persistence memory_store.search_limit_default must be less than or equal "
                "to memory_store.search_limit_max."
            )


def _find_fallback_cycle(
    profiles: Mapping[str, LLMProfileConfig],
) -> list[str] | None:
    visited: set[str] = set()
    visiting_positions: dict[str, int] = {}
    stack: list[str] = []

    def visit(profile_name: str) -> list[str] | None:
        if profile_name in visited:
            return None

        existing_position = visiting_positions.get(profile_name)
        if existing_position is not None:
            return stack[existing_position:] + [profile_name]

        visiting_positions[profile_name] = len(stack)
        stack.append(profile_name)

        for fallback_name in profiles[profile_name].fallback_profiles:
            if fallback_name not in profiles:
                continue
            cycle = visit(fallback_name)
            if cycle is not None:
                return cycle

        stack.pop()
        del visiting_positions[profile_name]
        visited.add(profile_name)
        return None

    for profile_name in profiles:
        cycle = visit(profile_name)
        if cycle is not None:
            return cycle

    return None


def _walk_for_literal_secrets(value: Any, *, segments: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _walk_for_literal_secrets(item, segments=[*segments, str(key)])
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_for_literal_secrets(item, segments=[*segments, f"[{index}]"])
        return

    if isinstance(value, tuple):
        for index, item in enumerate(value):
            _walk_for_literal_secrets(item, segments=[*segments, f"[{index}]"])
        return

    if not isinstance(value, str):
        return

    literal_value = value.strip()
    if not literal_value:
        return

    if not _segments_contain_sensitive_key(segments):
        return

    if has_env_reference(literal_value) or _is_dummy_secret(literal_value):
        return

    raise ConfigurationError(
        f"Refusing literal secret at config path '{_format_path(segments)}'. "
        f"Use an environment reference instead."
    )


def _segments_contain_sensitive_key(segments: list[str]) -> bool:
    for segment in segments:
        if segment.startswith("["):
            continue
        if is_sensitive_key(segment):
            return True
    return False


def _is_dummy_secret(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _DUMMY_SECRET_VALUES:
        return True

    return normalized.startswith(("dummy-", "test-", "example-", "placeholder-"))


def _format_path(segments: list[str]) -> str:
    path = ""
    for segment in segments:
        if segment.startswith("["):
            path = f"{path}{segment}"
            continue
        if not path:
            path = segment
            continue
        path = f"{path}.{segment}"
    return path or "<root>"


def _format_validation_error(error: Mapping[str, Any]) -> str:
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {error['msg']}"