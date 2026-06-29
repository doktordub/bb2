from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.contracts.errors import ConfigurationError

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"
BASE_FIXTURE_PATH = FIXTURES_DIR / "valid_minimal.yaml"


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        ("api_invalid_cors_origin.yaml", "api.cors.allow_origins"),
        ("api_invalid_request_limit.yaml", "api.request_limits.max_body_bytes"),
        ("api_invalid_timeout.yaml", "api.request_limits.request_timeout_seconds"),
        ("api_invalid_header_name.yaml", "api.sessions.session_id_header"),
    ],
)
def test_load_validated_config_rejects_invalid_api_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_body", "expected_message"),
    [
        (
            "session:\n"
            "  identifiers:\n"
            "    allowed_pattern: '[invalid'\n",
            "session.identifiers.allowed_pattern",
        ),
        (
            "session:\n"
            "  identifiers:\n"
            "    accept_client_session_id: false\n"
            "  lifecycle:\n"
            "    reject_unknown_client_session_id: true\n",
            "session.lifecycle.reject_unknown_client_session_id",
        ),
        (
            "api:\n"
            "  sessions:\n"
            "    create_session_when_missing: false\n"
            "session:\n"
            "  identifiers:\n"
            "    generate_when_missing: true\n",
            "api.sessions.create_session_when_missing",
        ),
        (
            "session:\n"
            "  management:\n"
            "    default_list_limit: 250\n"
            "    max_list_limit: 100\n",
            "session.management.default_list_limit",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_session_configuration(
    tmp_path: Path,
    override_body: str,
    expected_message: str,
) -> None:
    override_path = tmp_path / "invalid_session.yaml"
    override_path.write_text(override_body, encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=override_path,
            env={},
        )

    assert expected_message in str(exc_info.value)


def test_load_validated_config_rejects_restart_route_when_debug_routes_disabled(
    tmp_path: Path,
) -> None:
    override_path = tmp_path / "invalid_restart.yaml"
    override_path.write_text(
        "api:\n"
        "  debug_routes:\n"
        "    enabled: false\n"
        "    restart_enabled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=override_path,
            env={},
        )

    assert "api.debug_routes.restart_enabled" in str(exc_info.value)


def test_load_validated_config_rejects_disabled_llm_provider_fixture() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / "llm_disabled_provider.yaml",
            env={},
        )

    message = str(exc_info.value)
    assert "disabled provider 'disabled_provider'" in message


@pytest.mark.parametrize(
    ("override_body", "expected_message"),
    [
        (
            "llm:\n"
            "  profiles:\n"
            "    local_reasoning:\n"
            "      max_output_tokens: 512\n"
            "      max_total_tokens: 128\n",
            "max_total_tokens must be greater than or equal to max_output_tokens",
        ),
        (
            "llm:\n"
            "  providers:\n"
            "    local_provider:\n"
            "      base_url: not-a-url\n",
            "llm.providers.local_provider.base_url",
        ),
        (
            "llm:\n"
            "  profiles:\n"
            "    broken_allowlist:\n"
            "      provider: local_provider\n"
            "      model: broken-allowlist-model\n"
            "      allowed_for:\n"
            "        usecases:\n"
            "          - missing_usecase\n",
            "allowed_for.usecases",
        ),
        (
            "llm:\n"
            "  defaults:\n"
            "    profile: custom_reasoner\n"
            "  providers:\n"
            "    custom_reasoner_provider:\n"
            "      type: custom_http\n"
            "      enabled: true\n"
            "  profiles:\n"
            "    custom_reasoner:\n"
            "      provider: custom_reasoner_provider\n"
            "      model: custom-http-model\n",
            "enabled custom_http providers require endpoint",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_llm_configuration(
    tmp_path: Path,
    override_body: str,
    expected_message: str,
) -> None:
    override_path = tmp_path / "invalid_llm.yaml"
    override_path.write_text(override_body, encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=override_path,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        ("memory_invalid_chunking.yaml", "overlap_tokens must be less than max_tokens"),
        (
            "memory_invalid_scoring.yaml",
            "At least one scoring weight must be greater than zero",
        ),
        (
            "memory_invalid_scope_rules.yaml",
            "require_durable_scope_for_writes",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_memory_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        ("tooling_invalid_auth.yaml", "bearer auth requires token"),
        (
            "tooling_invalid_allowlist.yaml",
            "references unknown logical tool 'missing.logical.tool'",
        ),
        ("tooling_invalid_transport.yaml", "transport must be one of"),
    ],
)
def test_load_validated_config_rejects_invalid_tooling_fixture_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_body", "expected_message"),
    [
        (
            "tooling:\n"
            "  enabled: true\n"
            "mcp:\n"
            "  main:\n"
            "    enabled: false\n",
            "tooling.enabled requires mcp.main.enabled",
        ),
        (
            "features:\n"
            "  tools_enabled: true\n"
            "tooling:\n"
            "  enabled: true\n"
            "  registry:\n"
            "    tools:\n"
            "      documents.search:\n"
            "        enabled: true\n"
            "        mcp_tool_name: documents.search\n"
            "        allowed_for:\n"
            "          usecases:\n"
            "            - default_chat\n"
            "          agents:\n"
            "            - support_agent\n"
            "          strategies:\n"
            "            - direct_agent\n"
            "        input_schema_override:\n"
            "          - invalid\n",
            "input_schema_override",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_inline_tooling_configuration(
    tmp_path: Path,
    override_body: str,
    expected_message: str,
) -> None:
    override_path = tmp_path / "invalid_tooling.yaml"
    override_path.write_text(override_body, encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=override_path,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        (
            "orchestration_disabled_strategy.yaml",
            "Orchestration default strategy 'direct_agent' is disabled.",
        ),
        (
            "orchestration_unknown_usecase.yaml",
            "Active use case 'missing_chat' is not defined in usecases.",
        ),
        (
            "orchestration_limits.yaml",
            "max_stream_duration_seconds must be greater than or equal to max_turn_duration_seconds",
        ),
        (
            "orchestration_debug_unsafe_invalid.yaml",
            "orchestration.defaults.expose_chain_of_thought may only be enabled in local or test environments.",
        ),
        (
            "orchestration_invalid_missing_fallback.yaml",
            "Orchestration fallback strategy 'fallback_answer' is not defined.",
        ),
        (
            "orchestration_invalid_raw_mcp_tool.yaml",
            "references raw MCP tool name 'documents.search'. Use logical backend tool 'documents_search' instead.",
        ),
        (
            "orchestration_invalid_unbounded_planner.yaml",
            "Bounded planner strategy 'bounded_planner' requires max_plan_steps and max_execute_steps.",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_orchestration_fixture_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_body", "expected_message"),
    [
        (
            "memory:\n"
            "  enabled: false\n"
            "orchestration:\n"
            "  strategies:\n"
            "    retrieval_augmented:\n"
            "      enabled: true\n"
            "      type: retrieval_augmented\n"
            "      default_agent: support_agent\n"
            "      memory_enabled: true\n"
            "  usecases:\n"
            "    default_chat:\n"
            "      strategy: retrieval_augmented\n"
            "      agent: support_agent\n",
            "Strategy 'retrieval_augmented' enables memory but memory is disabled.",
        ),
        (
            "tooling:\n"
            "  enabled: false\n"
            "orchestration:\n"
            "  strategies:\n"
            "    tool_assisted:\n"
            "      enabled: true\n"
            "      type: tool_assisted\n"
            "      default_agent: support_agent\n"
            "      tools_enabled: true\n"
            "  usecases:\n"
            "    default_chat:\n"
            "      strategy: tool_assisted\n"
            "      agent: support_agent\n",
            "Strategy 'tool_assisted' enables tools but tooling is disabled.",
        ),
        (
            "memory:\n"
            "  enabled: true\n"
            "  lifecycle:\n"
            "    allow_writes: false\n"
            "orchestration:\n"
            "  defaults:\n"
            "    strategy: memory_update\n"
            "    fallback_strategy: direct_agent\n"
            "  strategies:\n"
            "    memory_update:\n"
            "      enabled: true\n"
            "      type: memory_update\n"
            "      default_agent: support_agent\n"
            "      allowed_usecases:\n"
            "        - default_chat\n"
            "      llm_profile: local_reasoning\n"
            "      memory_enabled: true\n"
            "      memory_write_enabled: true\n"
            "      require_policy_approval: true\n"
            "  usecases:\n"
            "    default_chat:\n"
            "      strategy: memory_update\n"
            "      agent: support_agent\n"
            "      allowed_agents:\n"
            "        - support_agent\n"
            "      policy_profile: default\n",
            "Memory-update strategy 'memory_update' requires memory.lifecycle.allow_writes to be true.",
        ),
        (
            "memory:\n"
            "  enabled: true\n"
            "  lifecycle:\n"
            "    allow_writes: true\n"
            "orchestration:\n"
            "  defaults:\n"
            "    strategy: memory_update\n"
            "    fallback_strategy: direct_agent\n"
            "  strategies:\n"
            "    memory_update:\n"
            "      enabled: true\n"
            "      type: memory_update\n"
            "      default_agent: support_agent\n"
            "      allowed_usecases:\n"
            "        - default_chat\n"
            "      llm_profile: local_reasoning\n"
            "      memory_enabled: true\n"
            "      memory_write_enabled: true\n"
            "      require_policy_approval: true\n"
            "  usecases:\n"
            "    default_chat:\n"
            "      strategy: memory_update\n"
            "      agent: support_agent\n"
            "      allowed_agents:\n"
            "        - support_agent\n"
            "      policy_profile: default\n",
            "Memory-update strategy 'memory_update' is selected by use case 'default_chat' but policy profile 'default' does not allow memory writes.",
        ),
    ],
)
def test_load_validated_config_rejects_orchestration_capability_mismatches(
    tmp_path: Path,
    override_body: str,
    expected_message: str,
) -> None:
    override_path = tmp_path / "invalid_orchestration.yaml"
    override_path.write_text(override_body, encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=override_path,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        (
            "agents_invalid_missing_llm_profile.yaml",
            "Agent 'support_agent' references unknown LLM profile 'missing_profile'.",
        ),
        (
            "agents_invalid_unknown_type.yaml",
            "agents.plugins.support_agent.type",
        ),
        (
            "agents_invalid_raw_mcp_tool.yaml",
            "references raw MCP tool name 'documents.search'. Use logical backend tool 'documents_search' instead.",
        ),
        (
            "agents_invalid_unbounded_self_managed.yaml",
            "max_self_managed_tool_calls",
        ),
        (
            "agents_invalid_memory_write_without_policy.yaml",
            "policy profile 'default' does not allow memory writes.",
        ),
        (
            "agents_invalid_disabled_reference.yaml",
            "references disabled default agent 'support_agent'.",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_agent_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        (
            "policy_invalid_unknown_reference.yaml",
            "Policy profile 'default' references unknown use case 'missing_usecase'.",
        ),
        (
            "policy_invalid_raw_trace.yaml",
            "policy.profiles.default.trace.expose_raw_payloads",
        ),
        (
            "policy_invalid_write_tool_without_approval.yaml",
            "enables write tools without requiring approval",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_policy_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        (
            "deployment_invalid_profile.yaml",
            "deployment.profile: Value error, profile must be one of:",
        ),
        (
            "deployment_invalid_path_escape.yaml",
            "deployment.log_dir must not point inside backend source package directories.",
        ),
    ],
)
def test_load_validated_config_rejects_invalid_deployment_fixture_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)


def test_load_validated_config_rejects_deployment_profile_mismatch(tmp_path: Path) -> None:
    override_path = tmp_path / "invalid_deployment.yaml"
    override_path.write_text(
        "deployment:\n"
        "  profile: production\n"
        "  log_dir: ../var/log/backend\n"
        "  runtime_dir: ../var/run/backend\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=override_path,
            env={},
        )

    assert "deployment.profile must match app.environment." in str(exc_info.value)