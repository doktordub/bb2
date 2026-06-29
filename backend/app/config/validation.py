"""Schema parsing and cross-reference validation for backend configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.config.env_resolver import has_env_reference
from app.config.redaction import is_sensitive_key
from app.config.schemas import (
    AgentConfig,
    BackendConfig,
    LLMProfileConfig,
    StoreConfig,
)
from app.config.view import ValidatedConfigurationView, get_deployment_settings
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
    agent_plugins = config.agents.plugins

    _validate_api_config(errors, config=config)
    _validate_session_config(errors, config=config)
    _validate_orchestration_config(errors, config=config)
    _validate_tooling_config(errors, config=config)
    _validate_agents_config(errors, config=config)
    _validate_deployment_config(errors, config=config)

    active_usecase = config.usecases.get(config.app.active_usecase)
    if active_usecase is None:
        errors.append(
            f"Active use case '{config.app.active_usecase}' is not defined in usecases."
        )
    elif not active_usecase.enabled:
        errors.append(f"Active use case '{config.app.active_usecase}' is disabled.")

    llm_profiles = config.llm.profiles
    policy_profiles = config.policy.profiles

    _validate_llm_config(errors, config=config)
    _validate_policy_config(errors, config=config)

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

        default_agent = agent_plugins.get(usecase.default_agent)
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

        _validate_known_tool_names(
            errors,
            owner_label=f"Use case '{usecase_name}'",
            allowed_tool_names=usecase.tools.allowed_tools,
            known_tool_names=set(config.tooling.registry.tools),
        )

        allowed_tool_names = set(usecase.tools.allowed_tools)
        for agent_name in usecase.allowed_agents:
            agent = agent_plugins.get(agent_name)
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

    for agent_name, agent in agent_plugins.items():
        if agent.llm_profile is not None and agent.llm_profile not in llm_profiles:
            errors.append(
                f"Agent '{agent_name}' references unknown LLM profile '{agent.llm_profile}'."
            )

        _validate_known_tool_names(
            errors,
            owner_label=f"Agent '{agent_name}'",
            allowed_tool_names=agent.allowed_tool_intents,
            known_tool_names=set(config.tooling.registry.tools),
        )

    _validate_store(errors, store_name="workflow_state", store=config.persistence.workflow_state)
    _validate_store(errors, store_name="trace", store=config.persistence.trace)
    _validate_memory_config(errors, config=config)

    if config.app.environment != "test" and not config.observability.redact_secrets:
        errors.append("observability.redact_secrets must remain enabled outside test environments.")

    if config.app.environment != "test" and config.health.expose_secret_values:
        errors.append("health.expose_secret_values must remain false outside test environments.")

    if errors:
        raise ConfigurationError("; ".join(errors))


def _validate_llm_config(errors: list[str], *, config: BackendConfig) -> None:
    llm_config = config.llm
    llm_profiles = llm_config.profiles
    llm_providers = llm_config.providers
    default_profile_name = llm_config.defaults.profile

    if default_profile_name not in llm_profiles:
        errors.append(f"LLM default profile '{default_profile_name}' is not defined.")
    else:
        default_profile = llm_profiles[default_profile_name]
        if not default_profile.enabled:
            errors.append(
                f"LLM default profile '{default_profile_name}' must be enabled."
            )
        default_provider = llm_providers.get(default_profile.provider)
        if default_provider is not None and not default_provider.enabled:
            errors.append(
                f"LLM default profile '{default_profile_name}' uses disabled provider "
                f"'{default_profile.provider}'."
            )

    for profile_name, profile in llm_profiles.items():
        provider = llm_providers.get(profile.provider)
        if provider is None:
            errors.append(
                f"LLM profile '{profile_name}' references unknown provider '{profile.provider}'."
            )
        elif profile.enabled and not provider.enabled:
            errors.append(
                f"LLM profile '{profile_name}' is enabled but provider "
                f"'{profile.provider}' is disabled."
            )

        _validate_llm_allowlist(
            errors,
            config=config,
            profile_name=profile_name,
            usecases=profile.allowed_for.usecases,
            agents=profile.allowed_for.agents,
            strategies=profile.allowed_for.strategies,
        )

        for fallback_name in profile.fallback_profiles:
            fallback_profile = llm_profiles.get(fallback_name)
            if fallback_profile is None:
                errors.append(
                    f"LLM profile '{profile_name}' references unknown fallback profile "
                    f"'{fallback_name}'."
                )
                continue
            if profile.enabled and not fallback_profile.enabled:
                errors.append(
                    f"LLM profile '{profile_name}' references disabled fallback profile "
                    f"'{fallback_name}'."
                )

    fallback_cycle = _find_fallback_cycle(llm_profiles)
    if fallback_cycle is not None:
        errors.append(f"LLM fallback cycle detected: {' -> '.join(fallback_cycle)}.")


def _validate_llm_allowlist(
    errors: list[str],
    *,
    config: BackendConfig,
    profile_name: str,
    usecases: list[str],
    agents: list[str],
    strategies: list[str],
) -> None:
    for usecase_name in usecases:
        if usecase_name not in config.usecases:
            errors.append(
                f"LLM profile '{profile_name}' references unknown use case "
                f"'{usecase_name}' in allowed_for.usecases."
            )

    for agent_name in agents:
        if agent_name not in config.agents.plugins:
            errors.append(
                f"LLM profile '{profile_name}' references unknown agent '{agent_name}' "
                f"in allowed_for.agents."
            )

    for strategy_name in strategies:
        if strategy_name not in config.strategies:
            errors.append(
                f"LLM profile '{profile_name}' references unknown strategy "
                f"'{strategy_name}' in allowed_for.strategies."
            )


def _validate_policy_config(errors: list[str], *, config: BackendConfig) -> None:
    from app.config.view import get_policy_settings

    try:
        settings = get_policy_settings(
            ValidatedConfigurationView(config.model_dump(mode="python"))
        )
    except ConfigurationError as exc:
        errors.append(str(exc))
        return

    known_usecases = set(config.usecases)
    known_strategies = set(config.strategies)
    known_agents = set(config.agents.plugins)
    known_llm_profiles = set(config.llm.profiles)
    known_tools = set(config.tooling.registry.tools)

    if settings.default_profile not in settings.profiles:
        errors.append(
            f"Policy default profile '{settings.default_profile}' is not defined."
        )

    for profile_name, profile in settings.profiles.items():
        for usecase_name in profile.usecases.allowed:
            if usecase_name not in known_usecases:
                errors.append(
                    f"Policy profile '{profile_name}' references unknown use case '{usecase_name}'."
                )

        for strategy_name in profile.strategies.allowed:
            if strategy_name not in known_strategies:
                errors.append(
                    f"Policy profile '{profile_name}' references unknown strategy '{strategy_name}'."
                )

        for agent_name in profile.agents.allowed:
            if agent_name not in known_agents:
                errors.append(
                    f"Policy profile '{profile_name}' references unknown agent '{agent_name}'."
                )

        for llm_profile_name in profile.llm.allowed_profiles:
            if llm_profile_name not in known_llm_profiles:
                errors.append(
                    f"Policy profile '{profile_name}' references unknown LLM profile '{llm_profile_name}'."
                )

        for tool_name in profile.tools.allowed_tools:
            if tool_name not in known_tools:
                errors.append(
                    f"Policy profile '{profile_name}' references unknown logical tool '{tool_name}'."
                )

        for fallback_strategy in profile.fallback.allowed_strategies:
            if fallback_strategy not in known_strategies:
                errors.append(
                    f"Policy profile '{profile_name}' references unknown fallback strategy '{fallback_strategy}'."
                )

        if profile.trace.expose_raw_payloads:
            errors.append(
                f"policy.profiles.{profile_name}.trace.expose_raw_payloads must remain false in V1."
            )

        if profile.trace.expose_prompt_text:
            errors.append(
                f"policy.profiles.{profile_name}.trace.expose_prompt_text must remain false in V1."
            )

        if profile.trace.expose_completion_text:
            errors.append(
                f"policy.profiles.{profile_name}.trace.expose_completion_text must remain false in V1."
            )

        if profile.stream.expose_raw_deltas:
            errors.append(
                f"policy.profiles.{profile_name}.stream.expose_raw_deltas must remain false in V1."
            )

        if (
            profile.tools.allow_write_tools
            and not profile.approval.require_approval_for_write_tools
        ):
            errors.append(
                f"Policy profile '{profile_name}' enables write tools without requiring approval."
            )

        if (
            profile.tools.allow_destructive_tools
            and not profile.approval.require_approval_for_destructive_tools
        ):
            errors.append(
                f"Policy profile '{profile_name}' enables destructive tools without requiring approval."
            )

        if (
            profile.tools.allow_external_side_effect_tools
            and not profile.approval.require_approval_for_external_side_effect_tools
        ):
            errors.append(
                "Policy profile "
                f"'{profile_name}' enables external-side-effect tools without requiring approval."
            )


def _validate_deployment_config(errors: list[str], *, config: BackendConfig) -> None:
    try:
        settings = get_deployment_settings(
            ValidatedConfigurationView(config.model_dump(mode="python"))
        )
    except ConfigurationError as exc:
        errors.append(str(exc))
        return

    if settings.profile != config.app.environment:
        errors.append("deployment.profile must match app.environment.")

    backend_root_parts = {"app", "config", "tests"}
    for field_name, path_value in (
        ("deployment.log_dir", settings.log_dir),
        ("deployment.runtime_dir", settings.runtime_dir),
    ):
        lowered_parts = {part.lower() for part in path_value.parts}
        if lowered_parts & backend_root_parts:
            errors.append(
                f"{field_name} must not point inside backend source package directories."
            )

    for field_name, path_value in (
        ("deployment.log_dir", settings.log_dir),
        ("deployment.runtime_dir", settings.runtime_dir),
    ):
        normalized = path_value.as_posix()
        if any(normalized.endswith(suffix) for suffix in ("/app", "/config", "/tests")):
            errors.append(
                f"{field_name} must not resolve inside backend source package directories."
            )

    if settings.public_base_url is not None:
        expected_suffix = f":{settings.port}"
        if settings.profile == "local" and settings.public_base_url.endswith(expected_suffix):
            pass

    if not config.observability.metrics_enabled and settings.metrics.enabled:
        errors.append(
            "deployment.metrics.enabled cannot be true when observability.metrics_enabled is false."
        )

    if settings.profile in {"staging", "production"}:
        for field_name, value in (
            ("deployment.log_dir", config.deployment.log_dir),
            ("deployment.runtime_dir", config.deployment.runtime_dir),
        ):
            normalized = value.replace("\\", "/").strip()
            if normalized in {"logs", "runtime"}:
                errors.append(
                    f"{field_name} must not use backend source defaults in {settings.profile} profile."
                )


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

    if api.debug_routes.restart_enabled and not api.debug_routes.enabled:
        errors.append(
            "api.debug_routes.restart_enabled requires api.debug_routes.enabled to be true."
        )


def _validate_session_config(errors: list[str], *, config: BackendConfig) -> None:
    session = config.session

    if session.defaults.default_usecase is not None:
        default_usecase = config.usecases.get(session.defaults.default_usecase)
        if default_usecase is None:
            errors.append(
                "session.defaults.default_usecase references an unknown use case."
            )
        elif not default_usecase.enabled:
            errors.append(
                "session.defaults.default_usecase references a disabled use case."
            )

    if (
        config.api.sessions.accept_client_session_id
        != session.identifiers.accept_client_session_id
    ):
        errors.append(
            "api.sessions.accept_client_session_id must match "
            "session.identifiers.accept_client_session_id."
        )

    if (
        config.api.sessions.create_session_when_missing
        != session.identifiers.generate_when_missing
    ):
        errors.append(
            "api.sessions.create_session_when_missing must match "
            "session.identifiers.generate_when_missing."
        )

    if (
        session.lifecycle.reject_unknown_client_session_id
        and not session.identifiers.accept_client_session_id
    ):
        errors.append(
            "session.lifecycle.reject_unknown_client_session_id requires "
            "session.identifiers.accept_client_session_id to be true."
        )

    if (
        session.lifecycle.save_after_cancelled_stream
        and not session.state.save_on_stream_cancellation
    ):
        errors.append(
            "session.lifecycle.save_after_cancelled_stream requires "
            "session.state.save_on_stream_cancellation to be true."
        )

    if session.management.default_list_limit > session.management.max_list_limit:
        errors.append(
            "session.management.default_list_limit must be less than or equal to "
            "session.management.max_list_limit."
        )


def _validate_tooling_config(errors: list[str], *, config: BackendConfig) -> None:
    from app.config.view import ValidatedConfigurationView, get_tooling_settings

    try:
        settings = get_tooling_settings(
            ValidatedConfigurationView(config.model_dump(mode="python"))
        )
    except ConfigurationError as exc:
        errors.append(str(exc))
        return

    if settings.enabled and not settings.mcp_server.enabled:
        errors.append("tooling.enabled requires mcp.main.enabled to be true.")

    known_usecases = set(config.usecases)
    known_agents = set(config.agents.plugins)
    known_strategies = set(config.strategies)

    for tool_name, definition in settings.registry.tools.items():
        if settings.registry.require_configured_allowlist and definition.enabled:
            if not (
                definition.allowed_for.usecases
                or definition.allowed_for.agents
                or definition.allowed_for.strategies
            ):
                errors.append(
                    f"Tool '{tool_name}' requires allowed_for metadata when "
                    "tooling.registry.require_configured_allowlist is true."
                )

        for usecase_name in definition.allowed_for.usecases:
            if usecase_name not in known_usecases:
                errors.append(
                    f"Tool '{tool_name}' references unknown use case '{usecase_name}' "
                    "in allowed_for.usecases."
                )

        for agent_name in definition.allowed_for.agents:
            if agent_name not in known_agents:
                errors.append(
                    f"Tool '{tool_name}' references unknown agent '{agent_name}' "
                    "in allowed_for.agents."
                )

        for strategy_name in definition.allowed_for.strategies:
            if strategy_name not in known_strategies:
                errors.append(
                    f"Tool '{tool_name}' references unknown strategy '{strategy_name}' "
                    "in allowed_for.strategies."
                )


def _validate_orchestration_config(errors: list[str], *, config: BackendConfig) -> None:
    from app.config.view import (
        ValidatedConfigurationView,
        get_memory_settings,
        get_orchestration_settings,
        get_tooling_settings,
    )

    view = ValidatedConfigurationView(config.model_dump(mode="python"))

    try:
        settings = get_orchestration_settings(view)
        memory_settings = get_memory_settings(view)
        tooling_settings = get_tooling_settings(view)
    except ConfigurationError as exc:
        errors.append(str(exc))
        return

    default_strategy = settings.strategies.get(settings.defaults.strategy)
    if default_strategy is None:
        errors.append(
            f"Orchestration default strategy '{settings.defaults.strategy}' is not defined."
        )
    elif not default_strategy.enabled:
        errors.append(
            f"Orchestration default strategy '{settings.defaults.strategy}' is disabled."
        )

    fallback_strategy = settings.strategies.get(settings.defaults.fallback_strategy)
    if fallback_strategy is None:
        errors.append(
            "Orchestration fallback strategy "
            f"'{settings.defaults.fallback_strategy}' is not defined."
        )
    elif not fallback_strategy.enabled:
        errors.append(
            "Orchestration fallback strategy "
            f"'{settings.defaults.fallback_strategy}' is disabled."
        )

    if settings.defaults.expose_chain_of_thought and config.app.environment not in {
        "local",
        "test",
    }:
        errors.append(
            "orchestration.defaults.expose_chain_of_thought may only be enabled in local or test environments."
        )

    if settings.defaults.save_runtime_snapshots and config.app.environment not in {
        "local",
        "test",
    }:
        errors.append(
            "orchestration.defaults.save_runtime_snapshots may only be enabled in local or test environments."
        )

    known_llm_profiles = set(config.llm.profiles)
    known_tool_names = set(tooling_settings.registry.tools)
    mcp_tool_name_to_logical_name = {
        tool.mcp_tool_name: tool_name
        for tool_name, tool in tooling_settings.registry.tools.items()
        if tool.mcp_tool_name != tool_name
    }

    for strategy_name, strategy in settings.strategies.items():
        if strategy.llm_profile is not None and strategy.llm_profile not in known_llm_profiles:
            errors.append(
                f"Strategy '{strategy_name}' references unknown LLM profile '{strategy.llm_profile}'."
            )

        if (
            strategy.planner_llm_profile is not None
            and strategy.planner_llm_profile not in known_llm_profiles
        ):
            errors.append(
                "Strategy "
                f"'{strategy_name}' references unknown planner LLM profile "
                f"'{strategy.planner_llm_profile}'."
            )

        if (
            strategy.executor_llm_profile is not None
            and strategy.executor_llm_profile not in known_llm_profiles
        ):
            errors.append(
                "Strategy "
                f"'{strategy_name}' references unknown executor LLM profile "
                f"'{strategy.executor_llm_profile}'."
            )

        if not strategy.enabled:
            continue

        if strategy.memory_enabled and not memory_settings.enabled:
            errors.append(
                f"Strategy '{strategy_name}' enables memory but memory is disabled."
            )

        if strategy.memory_write_enabled and not strategy.memory_enabled:
            errors.append(
                f"Strategy '{strategy_name}' enables memory writes but memory is not enabled."
            )

        if strategy.tools_enabled and not tooling_settings.enabled:
            errors.append(
                f"Strategy '{strategy_name}' enables tools but tooling is disabled."
            )

        if strategy.fallback_strategy is not None:
            fallback = settings.strategies.get(strategy.fallback_strategy)
            if fallback is None:
                errors.append(
                    f"Strategy '{strategy_name}' references unknown fallback strategy '{strategy.fallback_strategy}'."
                )
            elif not fallback.enabled:
                errors.append(
                    f"Strategy '{strategy_name}' references disabled fallback strategy '{strategy.fallback_strategy}'."
                )

        for candidate_name in strategy.candidate_strategies:
            candidate_strategy = settings.strategies.get(candidate_name)
            if candidate_strategy is None:
                errors.append(
                    f"Strategy '{strategy_name}' references unknown candidate strategy '{candidate_name}'."
                )
            elif not candidate_strategy.enabled:
                errors.append(
                    f"Strategy '{strategy_name}' references disabled candidate strategy '{candidate_name}'."
                )

        if strategy.tools.allowed_tools:
            _validate_orchestration_tool_names(
                errors,
                owner_label=f"Strategy '{strategy_name}'",
                allowed_tool_names=strategy.tools.allowed_tools,
                known_tool_names=known_tool_names,
                mcp_tool_name_to_logical_name=mcp_tool_name_to_logical_name,
            )

        if strategy.type == "bounded_planner" and strategy.enabled:
            if strategy.max_plan_steps is None or strategy.max_execute_steps is None:
                errors.append(
                    f"Bounded planner strategy '{strategy_name}' requires max_plan_steps and max_execute_steps."
                )

        if strategy.type == "memory_update" and strategy.enabled:
            if not strategy.memory_enabled:
                errors.append(
                    f"Memory-update strategy '{strategy_name}' requires memory_enabled to be true."
                )
            if not strategy.memory_write_enabled:
                errors.append(
                    f"Memory-update strategy '{strategy_name}' requires memory_write_enabled to be true."
                )
            if not memory_settings.lifecycle.allow_writes:
                errors.append(
                    f"Memory-update strategy '{strategy_name}' requires memory.lifecycle.allow_writes to be true."
                )

            selected_usecases = [
                usecase
                for usecase in settings.usecases.values()
                if usecase.enabled and usecase.strategy == strategy_name
            ]
            for usecase in selected_usecases:
                policy_profile = config.policy.profiles.get(usecase.policy_profile)
                if policy_profile is None:
                    continue
                if not policy_profile.allow_memory_writes:
                    errors.append(
                        "Memory-update strategy "
                        f"'{strategy_name}' is selected by use case '{usecase.name}' but "
                        f"policy profile '{usecase.policy_profile}' does not allow memory writes."
                    )

    for usecase_name, usecase in settings.usecases.items():
        if not usecase.enabled:
            continue

        resolved_strategy = settings.strategies.get(usecase.strategy)
        if resolved_strategy is None:
            errors.append(
                f"Use case '{usecase_name}' references unknown orchestration strategy '{usecase.strategy}'."
            )
            continue

        if not resolved_strategy.enabled:
            errors.append(
                f"Use case '{usecase_name}' references disabled orchestration strategy '{usecase.strategy}'."
            )

        for allowed_strategy_name in usecase.allowed_strategies:
            allowed_strategy = settings.strategies.get(allowed_strategy_name)
            if allowed_strategy is None:
                errors.append(
                    f"Use case '{usecase_name}' references unknown allowed strategy '{allowed_strategy_name}'."
                )
            elif not allowed_strategy.enabled:
                errors.append(
                    f"Use case '{usecase_name}' references disabled allowed strategy '{allowed_strategy_name}'."
                )

        if usecase.allowed_strategies and usecase.strategy not in usecase.allowed_strategies:
            errors.append(
                f"Use case '{usecase_name}' must include its selected strategy '{usecase.strategy}' in allowed_strategies."
            )


def _validate_agents_config(errors: list[str], *, config: BackendConfig) -> None:
    from app.config.view import (
        ValidatedConfigurationView,
        get_agents_settings,
        get_memory_settings,
        get_tooling_settings,
    )

    view = ValidatedConfigurationView(config.model_dump(mode="python"))

    try:
        settings = get_agents_settings(view)
        memory_settings = get_memory_settings(view)
        tooling_settings = get_tooling_settings(view)
    except ConfigurationError as exc:
        errors.append(str(exc))
        return

    mcp_tool_name_to_logical_name = {
        tool.mcp_tool_name: tool_name
        for tool_name, tool in tooling_settings.registry.tools.items()
        if tool.mcp_tool_name != tool_name
    }

    if not settings.enabled and any(plugin.enabled for plugin in settings.plugins.values()):
        errors.append(
            "agents.defaults.enabled must be true when agent plugins are enabled."
        )

    for agent_name, agent in settings.plugins.items():
        if not agent.enabled:
            continue

        if settings.strict_prompt_profile_validation:
            if agent.prompt_profile is None:
                errors.append(
                    f"Agent '{agent_name}' requires prompt_profile when strict prompt validation is enabled."
                )
            elif agent.prompt_profile not in set(settings.known_prompt_profiles):
                errors.append(
                    f"Agent '{agent_name}' references unknown prompt profile '{agent.prompt_profile}'."
                )

        if "*" in agent.allowed_tool_intents:
            errors.append(
                f"Agent '{agent_name}' may not allow all tool intents via wildcard in V1."
            )

        _validate_orchestration_tool_names(
            errors,
            owner_label=f"Agent '{agent_name}'",
            allowed_tool_names=agent.allowed_tool_intents,
            known_tool_names=set(tooling_settings.registry.tools),
            mcp_tool_name_to_logical_name=mcp_tool_name_to_logical_name,
        )

        if agent.allowed_tool_intents and not (
            agent.capabilities.tool_intents or agent.capabilities.tool_execute
        ):
            errors.append(
                f"Agent '{agent_name}' declares allowed_tool_intents without a tool capability."
            )

        if (
            agent.capabilities.tool_intents
            or agent.capabilities.tool_execute
            or agent.allowed_tool_intents
        ) and not tooling_settings.enabled:
            errors.append(
                f"Agent '{agent_name}' enables tool use but tooling is disabled."
            )

        if (
            agent.capabilities.memory_read
            or agent.capabilities.memory_write
            or agent.capabilities.self_managed_memory
        ) and not memory_settings.enabled:
            errors.append(
                f"Agent '{agent_name}' enables memory use but memory is disabled."
            )

        if agent.capabilities.memory_write:
            if not memory_settings.lifecycle.allow_writes:
                errors.append(
                    f"Agent '{agent_name}' enables memory writes but memory.lifecycle.allow_writes is false."
                )
            if not settings.allow_memory_write:
                errors.append(
                    f"Agent '{agent_name}' enables memory writes but agents.defaults.allow_memory_write is false."
                )

            for usecase_name, usecase in config.orchestration.usecases.items():
                if not usecase.enabled:
                    continue
                if usecase.agent != agent_name and agent_name not in usecase.allowed_agents:
                    continue

                policy_profile = config.policy.profiles.get(usecase.policy_profile)
                if policy_profile is None or not policy_profile.allow_memory_writes:
                    errors.append(
                        "Memory-writing agent "
                        f"'{agent_name}' is selected by use case '{usecase_name}' but "
                        f"policy profile '{usecase.policy_profile}' does not allow memory writes."
                    )

        if agent.capabilities.tool_execute and not agent.capabilities.self_managed_tools:
            errors.append(
                f"Agent '{agent_name}' enables tool_execute without self_managed_tools."
            )

        if agent.capabilities.self_managed_tools:
            if not settings.allow_self_managed_tools:
                errors.append(
                    f"Agent '{agent_name}' enables self-managed tools but agents.defaults.allow_self_managed_tools is false."
                )
            if agent.limits.max_self_managed_tool_calls <= 0:
                errors.append(
                    f"Agent '{agent_name}' enables self-managed tools without a positive max_self_managed_tool_calls limit."
                )

        if agent.capabilities.self_managed_memory:
            if not settings.allow_self_managed_memory:
                errors.append(
                    f"Agent '{agent_name}' enables self-managed memory but agents.defaults.allow_self_managed_memory is false."
                )
            if agent.limits.max_self_managed_memory_searches <= 0:
                errors.append(
                    f"Agent '{agent_name}' enables self-managed memory without a positive max_self_managed_memory_searches limit."
                )


def _validate_orchestration_tool_names(
    errors: list[str],
    *,
    owner_label: str,
    allowed_tool_names: tuple[str, ...],
    known_tool_names: set[str],
    mcp_tool_name_to_logical_name: dict[str, str],
) -> None:
    for tool_name in allowed_tool_names:
        if tool_name in known_tool_names:
            continue
        logical_name = mcp_tool_name_to_logical_name.get(tool_name)
        if logical_name is not None:
            errors.append(
                f"{owner_label} references raw MCP tool name '{tool_name}'. Use logical backend tool '{logical_name}' instead."
            )
            continue
        errors.append(f"{owner_label} references unknown logical tool '{tool_name}'.")


def _validate_known_tool_names(
    errors: list[str],
    *,
    owner_label: str,
    allowed_tool_names: list[str],
    known_tool_names: set[str],
) -> None:
    for tool_name in allowed_tool_names:
        if tool_name not in known_tool_names:
            errors.append(
                f"{owner_label} references unknown logical tool '{tool_name}'."
            )


def _validate_agent_tool_subset(
    errors: list[str],
    *,
    usecase_name: str,
    usecase_tools_enabled: bool,
    allowed_tool_names: set[str],
    agent_name: str,
    agent: AgentConfig,
) -> None:
    if not agent.allowed_tool_intents:
        return

    if not usecase_tools_enabled:
        errors.append(
            f"Agent '{agent_name}' allows tools {sorted(set(agent.allowed_tool_intents))} but use case '{usecase_name}' disables tools."
        )
        return

    disallowed_tools = sorted(set(agent.allowed_tool_intents) - allowed_tool_names)
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


def _validate_memory_config(errors: list[str], *, config: BackendConfig) -> None:
    from app.config.view import ValidatedConfigurationView, get_memory_settings

    try:
        settings = get_memory_settings(
            ValidatedConfigurationView(config.model_dump(mode="python"))
        )
    except ConfigurationError as exc:
        errors.append(str(exc))
        return

    allowed_providers = {"disabled", "fake", "memory_store", "none"}
    if settings.provider not in allowed_providers:
        supported = ", ".join(sorted(allowed_providers))
        errors.append(f"memory.provider must be one of: {supported}.")

    if settings.search.graph_expansion_hops not in {0, 1}:
        errors.append("memory.search.graph_expansion_hops must remain within the V1 0..1 bound.")

    if settings.chunking.overlap_tokens >= settings.chunking.max_tokens:
        errors.append("memory.chunking.overlap_tokens must be less than memory.chunking.max_tokens.")

    if settings.defaults.top_k > settings.search.limit_max:
        errors.append("memory.defaults.top_k must be less than or equal to memory.search.limit_max.")

    if settings.search.final_top_k > settings.search.limit_max:
        errors.append("memory.search.final_top_k must be less than or equal to memory.search.limit_max.")

    weight_sum = sum(
        getattr(settings.scoring.weights, field_name)
        for field_name in (
            "reranker",
            "retrieval_fusion",
            "vector",
            "full_text",
            "temporal",
            "importance",
            "confidence",
            "graph",
            "user_rating",
        )
    )
    if weight_sum <= 0:
        errors.append("memory.scoring.weights must sum to more than zero.")

    default_policy = config.policy.profiles.get(config.policy.default_profile)
    if settings.lifecycle.allow_writes and not settings.lifecycle.require_durable_scope_for_writes:
        errors.append(
            "memory.lifecycle.allow_writes requires memory.lifecycle.require_durable_scope_for_writes to remain true."
        )

    if default_policy is not None and default_policy.require_memory_scope and not settings.lifecycle.require_durable_scope_for_writes:
        errors.append(
            "memory.lifecycle.require_durable_scope_for_writes must remain true when the default policy requires memory scope."
        )

    if default_policy is not None and default_policy.allow_memory_writes and not settings.lifecycle.require_durable_scope_for_writes:
        errors.append(
            "memory lifecycle scope rules are incompatible with the default policy write settings."
        )

    if (
        settings.privacy.enable_delete_by_scope
        or settings.privacy.enable_export_by_scope
    ) and not settings.lifecycle.require_durable_scope_for_delete_export:
        errors.append(
            "memory delete/export operations require memory.lifecycle.require_durable_scope_for_delete_export to remain true."
        )

    if (
        config.app.environment != "test"
        and (settings.privacy.enable_delete_by_scope or settings.privacy.enable_export_by_scope)
        and not settings.privacy.require_policy_approval_for_delete_export
    ):
        errors.append(
            "memory delete/export settings must require policy approval outside test environments."
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
        if segment in {"auth", "oauth"}:
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