# Configuration Architecture

**Document:** `configuration-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, and `backend-core-contracts-architecture.md`  
**Scope:** YAML configuration structure, environment variable resolution, schema validation, configuration loading flow, runtime configuration access, startup validation, test strategy, and acceptance criteria for the backend application tier.

---

## 1. Purpose

This document defines the third implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `configuration-architecture.md` ← this document

The foundation phase establishes the backend skeleton, application factory, local startup pattern, settings loader, health route, logging baseline, and test layout. The core contracts phase defines the stable DTOs, protocols, context objects, gateway contracts, fake implementations, and `ConfigurationView` / `ConfigurationLoader` contracts.

This document turns the configuration contract into an implementation architecture. It defines how the backend loads YAML, resolves environment variables, validates schema, exposes a read-only configuration view, and wires use cases, agents, strategies, LLM profiles, MCP endpoint, persistence providers, policy defaults, feature flags, and observability settings.

The goal is to make runtime behavior configuration-driven before concrete LLM, memory, MCP, workflow state, trace, orchestration, and agent implementations depend on configuration.

---

## 2. Source Architecture Alignment

This document follows the established backend architecture rules:

- The backend is one deployable application tier in V1.
- The frontend communicates with the backend over REST / SSE.
- The backend communicates with the external MCP tier through a backend-side MCP client adapter.
- The backend does not implement the MCP server.
- Agents receive controlled capabilities through `OrchestrationContext`.
- Agents do not import provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, external API clients, or `memory_store.service.MemoryService`.
- Runtime code should access configuration through `ConfigurationView`, not raw dictionaries or raw environment variables.
- Provider, model, endpoint, tool, persistence, and policy details belong in YAML and environment variables, not inside agents or API routes.
- LLM provider and model selection must use logical profiles.
- Orchestrator and agents can use different LLM profiles.
- Unknown LLM profiles and unknown tools should be denied by default in real implementations.
- SQLite and ArcadeDB remain implementation details behind backend adapters.
- Full YAML schema validation begins in this phase.

---

## 3. Position in the Backend Implementation Sequence

The backend implementation sequence is:

```text
Phase 1: Backend Foundation Skeleton
Phase 2: Core Contracts
Phase 3: Configuration Loader
Phase 4: Observability and Trace Foundation
Phase 5: Workflow State Store
Phase 6: API and Session Walking Skeleton
Phase 7: LLM Gateway
Phase 8: Memory Gateway
Phase 9: Tool Gateway and MCP Client Adapter
Phase 10: Orchestration Runtime and Strategies
Phase 11: Agent Plugins
Phase 12: Hardening and Deployment Readiness
```

This document expands Phase 3.

The output of this phase is not a working agentic runtime yet. The output is a validated configuration system that later modules can depend on without hard-coding runtime decisions.

---

## 4. Configuration Architecture Goals

The configuration layer should be:

1. **Single source of runtime wiring**  
   Use cases, agents, strategies, LLM profiles, MCP endpoints, persistence providers, policy defaults, and feature flags are configured centrally.

2. **Environment-aware**  
   Local, test, and future deployment environments can use different YAML files and environment variables without changing code.

3. **Schema-validated**  
   Invalid configuration fails fast during startup with useful errors.

4. **Provider-neutral**  
   Agents and strategies reference logical LLM profiles, not provider SDKs, model URLs, or API keys.

5. **Secret-safe**  
   Secrets are never committed in YAML and are never printed in logs, health responses, traces, or validation errors.

6. **Composable**  
   The backend can support a base config plus environment-specific overrides.

7. **Runtime-stable**  
   The loaded config is immutable or treated as read-only for V1.

8. **Testable**  
   Unit tests can load sample configs, validate failure cases, and use `FakeConfigurationView` without real providers.

9. **Dependency-aware**  
   Later modules can resolve configuration through narrow helpers instead of walking raw nested dictionaries.

---

## 5. Configuration Non-Goals

This phase should not implement:

- Real LLM provider calls.
- Real MCP client calls.
- Real SQLite stores.
- Real `memory_store` / ArcadeDB integration.
- Full policy engine behavior.
- Agent business behavior.
- Runtime hot reload.
- Distributed configuration service.
- Secret manager integration beyond environment variable references.
- Complex multi-tenant configuration inheritance.
- Frontend configuration management.

Those belong in later architecture and implementation phases.

---

## 6. Recommended Configuration Package Layout

Recommended layout:

```text
backend/
  app/
    config/
      __init__.py
      settings.py
      loader.py
      schemas.py
      view.py
      env_resolver.py
      validation.py
      redaction.py
      bootstrap.py

    contracts/
      config.py
      errors.py

    testing/
      fakes/
        fake_config.py

  config/
    app.yaml
    app.local.yaml optional
    app.test.yaml optional
    usecases/
      default.yaml optional future split

  tests/
    unit/
      config/
        test_settings.py
        test_env_resolver.py
        test_loader_valid_config.py
        test_loader_invalid_config.py
        test_config_view.py
        test_redaction.py
        test_cross_reference_validation.py

    fixtures/
      config/
        valid_minimal.yaml
        valid_full.yaml
        invalid_missing_active_usecase.yaml
        invalid_unknown_llm_profile.yaml
        invalid_unknown_agent.yaml
        invalid_secret_literal.yaml
```

### 6.1 Why `app/config/` Is Separate from `app/contracts/config.py`

`app/contracts/config.py` defines the stable protocol:

```python
class ConfigurationView(Protocol):
    def get(self, path: str, default: Any = None) -> Any:
        ...

    def require(self, path: str) -> Any:
        ...

    def section(self, path: str) -> dict[str, Any]:
        ...


class ConfigurationLoader(Protocol):
    async def load(self) -> ConfigurationView:
        ...
```

`app/config/` provides the concrete implementation:

```text
YamlConfigurationLoader
Pydantic schema models
Environment variable resolver
ValidatedConfigurationView
Redaction utilities
Bootstrap helpers
```

Contracts remain infrastructure-light. Configuration implementation can use YAML and Pydantic because this phase owns validation at the configuration boundary.

---

## 7. Dependency Direction Rules

Allowed:

```text
app/main.py                 -> app/config/bootstrap.py
app/config/bootstrap.py     -> app/config/loader.py
app/config/loader.py        -> app/config/schemas.py
app/config/loader.py        -> app/config/env_resolver.py
app/config/view.py          -> app/contracts/config.py
app/llm/profile_resolver.py -> app/contracts/config.py
app/agents/registry.py      -> app/contracts/config.py
app/tools/gateway.py        -> app/contracts/config.py
```

Avoid:

```text
app/contracts/config.py -> app/config/loader.py
app/contracts/config.py -> pydantic
app/agents/*           -> os.environ
app/agents/*           -> raw YAML parser
app/api/*              -> provider/model endpoint strings
app/llm/providers/*    -> agent registry
app/tools/*            -> orchestration runtime
```

The composition root may import concrete configuration classes. Most runtime modules should depend only on `ConfigurationView` or typed resolver helpers.

---

## 8. Configuration Source Model

V1 should support these configuration sources:

| Source | Purpose | Example |
|---|---|---|
| Environment variables | Secrets, deployment-specific paths, active config path | `APP_CONFIG_PATH`, `OPENAI_API_KEY`, `MCP_MAIN_URL` |
| Base YAML | Default backend runtime wiring | `config/app.yaml` |
| Optional override YAML | Local/test environment differences | `config/app.local.yaml`, `config/app.test.yaml` |
| Test fixtures | Deterministic unit/integration config | `tests/fixtures/config/valid_minimal.yaml` |

### 8.1 Recommended Source Precedence

Use this precedence, highest first:

```text
1. Explicit test override passed to loader
2. Environment-selected config path: APP_CONFIG_PATH
3. Environment-specific override YAML: APP_ENV=local -> app.local.yaml
4. Base YAML: config/app.yaml
5. Code defaults in schema models, only for safe non-secret defaults
```

### 8.2 Runtime Environment Variables

Recommended settings variables:

```env
APP_ENV=local
APP_CONFIG_PATH=./config/app.yaml
APP_CONFIG_OVERRIDE_PATH=./config/app.local.yaml
APP_LOG_LEVEL=INFO
APP_DATA_DIR=./data

MCP_MAIN_URL=http://localhost:9001/mcp

LOCAL_LLM_BASE_URL=http://192.168.1.80:8081/v1
LOCAL_LLM_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
```

Only non-secret defaults should appear in checked-in `.env.example` files.

---

## 9. Environment Variable Resolution

YAML should support explicit environment references. Recommended syntax:

```yaml
base_url: ${env:LOCAL_LLM_BASE_URL}
api_key: ${env:OPENAI_API_KEY}
path: ${env:APP_DATA_DIR}/workflow_state.db
optional_api_key: ${env:LOCAL_LLM_API_KEY:}
timeout_seconds: ${env:LLM_TIMEOUT_SECONDS:60}
```

Supported forms:

| Syntax | Meaning |
|---|---|
| `${env:VAR_NAME}` | Required environment variable. Fail if missing or empty. |
| `${env:VAR_NAME:default}` | Optional environment variable with default value. |
| `${env:VAR_NAME:}` | Optional environment variable with empty-string default. |

### 9.1 Resolution Rules

The resolver should:

- Resolve environment references before Pydantic schema validation.
- Fail fast for missing required variables.
- Preserve type validation for resolved values through the schema layer.
- Support references inside strings, not just as whole values.
- Avoid recursive interpolation in V1 unless explicitly needed.
- Never print resolved secret values in errors or logs.

### 9.2 Secret Handling Rule

Any key containing these terms should be treated as sensitive:

```text
api_key
apikey
token
secret
password
credential
authorization
```

Sensitive values must be redacted in:

- Logs.
- Health responses.
- Validation error summaries.
- Trace events.
- Debug dumps.
- Test snapshots.

---

## 10. Configuration File Organization

For V1, use one main YAML file for simplicity:

```text
config/app.yaml
```

As the system grows, large sections can be split into multiple files:

```text
config/
  app.yaml
  llm.yaml
  agents.yaml
  usecases.yaml
  tools.yaml
  persistence.yaml
  policy.yaml
```

The V1 loader should not require multi-file support. If implemented, multi-file support should be simple and deterministic.

---

## 11. Top-Level YAML Shape

Recommended top-level shape:

```yaml
app:
  name: pluggable-agentic-backend
  environment: local
  active_usecase: default_chat
  data_dir: ${env:APP_DATA_DIR:./data}

features:
  streaming_enabled: true
  memory_enabled: true
  tools_enabled: true
  trace_enabled: true

usecases:
  default_chat:
    enabled: true
    description: Default chat use case
    strategy: direct_agent
    default_agent: support_agent
    allowed_agents:
      - support_agent
    orchestrator_llm_profile: local_reasoning
    memory:
      enabled: true
      include_document_chunks: true
      default_limit: 8
    tools:
      enabled: true
      allowed_tools:
        - documents.search
    policy_profile: default

strategies:
  direct_agent:
    enabled: true
    type: direct
    description: Runs the default configured agent.
  router:
    enabled: false
    type: router
    llm_profile: local_reasoning
    max_candidate_agents: 3

agents:
  support_agent:
    enabled: true
    module: app.agents.support_agent
    class_name: SupportAgent
    description: General support and document-aware assistant.
    capabilities:
      - chat
      - document_qa
    llm_profile: local_reasoning
    allowed_tools:
      - documents.search
    memory:
      search_enabled: true
      write_enabled: false
    prompts:
      system_prompt: prompts/support_agent/system.md

llm:
  default_profile: local_reasoning
  providers:
    local_openai_compatible:
      type: openai_compatible
      base_url: ${env:LOCAL_LLM_BASE_URL}
      api_key: ${env:LOCAL_LLM_API_KEY:}
      timeout_seconds: 90
      default_headers: {}
    openai:
      type: openai
      api_key: ${env:OPENAI_API_KEY:}
      timeout_seconds: 60
  profiles:
    local_reasoning:
      provider: local_openai_compatible
      model: qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1
      temperature: 0.7
      max_tokens: 2048
      timeout_seconds: 90
      fallback_profiles: []
    cloud_fast:
      provider: openai
      model: gpt-4.1-mini
      temperature: 0.2
      max_tokens: 1024
      fallback_profiles:
        - local_reasoning

mcp:
  main:
    url: ${env:MCP_MAIN_URL:http://localhost:9001/mcp}
    timeout_seconds: 30
    tool_discovery_enabled: true

persistence:
  workflow_state:
    provider: sqlite
    path: ${env:APP_DATA_DIR:./data}/workflow_state.db
  trace:
    provider: sqlite
    path: ${env:APP_DATA_DIR:./data}/trace.db
  memory:
    provider: memory_store
    config:
      database_path: ${env:MEMORY_STORE_DB_PATH:./data/memory}
      default_scope: project

policy:
  default_profile: default
  profiles:
    default:
      deny_unknown_tools: true
      deny_unknown_llm_profiles: true
      require_memory_scope: true
      allow_memory_writes: false

observability:
  log_level: ${env:APP_LOG_LEVEL:INFO}
  structured_logging: true
  trace_payloads_enabled: true
  redact_secrets: true

health:
  expose_config_summary: true
  expose_provider_names: true
  expose_secret_values: false
```

---

## 12. Top-Level Section Responsibilities

| Section | Responsibility | Later Modules That Depend on It |
|---|---|---|
| `app` | Application identity, environment, active use case, data directory | Composition root, health, startup |
| `features` | Coarse feature flags | API, orchestration, tools, memory, tracing |
| `usecases` | Runtime workflow selection | Session service, orchestration runtime, policy |
| `strategies` | Strategy registry wiring | Orchestration runtime, strategy registry |
| `agents` | Agent registry wiring | Agent registry, orchestration runtime |
| `llm.providers` | Provider connection details | LLM gateway and provider adapters |
| `llm.profiles` | Logical model profiles | LLM gateway, agents, strategies |
| `mcp` | Single MCP endpoint and client defaults | Tool gateway and MCP client adapter |
| `persistence` | State, trace, memory adapter settings | Persistence adapters |
| `policy` | Deny-by-default behavior and profile rules | Policy service |
| `observability` | Logs, trace payload defaults, redaction behavior | Observability, trace store, gateways |
| `health` | Safe health summary behavior | API health routes |

---

## 13. Schema Validation Strategy

Use Pydantic models in `app/config/schemas.py` for external configuration validation.

Pydantic is appropriate here because YAML is an external boundary. This does not conflict with the contract rule that internal DTOs and gateway contracts should remain framework-light.

Recommended schema model groups:

```text
AppConfig
FeatureConfig
UseCaseConfig
StrategyConfig
AgentConfig
LLMConfig
LLMProviderConfig
LLMProfileConfig
MCPConfig
PersistenceConfig
PolicyConfig
ObservabilityConfig
HealthConfig
BackendConfig
```

### 13.1 Recommended Pydantic Model Sketch

```python
from pydantic import BaseModel, Field, ConfigDict


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppConfig(StrictConfigModel):
    name: str
    environment: str = "local"
    active_usecase: str
    data_dir: str = "./data"


class FeatureConfig(StrictConfigModel):
    streaming_enabled: bool = True
    memory_enabled: bool = True
    tools_enabled: bool = True
    trace_enabled: bool = True


class UseCaseMemoryConfig(StrictConfigModel):
    enabled: bool = True
    include_document_chunks: bool = True
    default_limit: int = Field(default=10, ge=1, le=100)


class UseCaseToolConfig(StrictConfigModel):
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)


class UseCaseConfig(StrictConfigModel):
    enabled: bool = True
    description: str | None = None
    strategy: str
    default_agent: str
    allowed_agents: list[str]
    orchestrator_llm_profile: str | None = None
    memory: UseCaseMemoryConfig = Field(default_factory=UseCaseMemoryConfig)
    tools: UseCaseToolConfig = Field(default_factory=UseCaseToolConfig)
    policy_profile: str = "default"


class StrategyConfig(StrictConfigModel):
    enabled: bool = True
    type: str
    description: str | None = None
    llm_profile: str | None = None
    max_candidate_agents: int | None = Field(default=None, ge=1, le=20)
    metadata: dict = Field(default_factory=dict)


class AgentMemoryConfig(StrictConfigModel):
    search_enabled: bool = True
    write_enabled: bool = False


class AgentPromptConfig(StrictConfigModel):
    system_prompt: str | None = None
    developer_prompt: str | None = None


class AgentConfig(StrictConfigModel):
    enabled: bool = True
    module: str
    class_name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    llm_profile: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    memory: AgentMemoryConfig = Field(default_factory=AgentMemoryConfig)
    prompts: AgentPromptConfig = Field(default_factory=AgentPromptConfig)
    metadata: dict = Field(default_factory=dict)


class LLMProviderConfig(StrictConfigModel):
    type: str
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    default_headers: dict[str, str] = Field(default_factory=dict)


class LLMProfileConfig(StrictConfigModel):
    provider: str
    model: str
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    fallback_profiles: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class LLMConfig(StrictConfigModel):
    default_profile: str
    providers: dict[str, LLMProviderConfig]
    profiles: dict[str, LLMProfileConfig]


class MCPServerConfig(StrictConfigModel):
    url: str
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    tool_discovery_enabled: bool = True


class MCPConfig(StrictConfigModel):
    main: MCPServerConfig


class StoreConfig(StrictConfigModel):
    provider: str
    path: str | None = None
    config: dict = Field(default_factory=dict)


class PersistenceConfig(StrictConfigModel):
    workflow_state: StoreConfig
    trace: StoreConfig
    memory: StoreConfig


class PolicyProfileConfig(StrictConfigModel):
    deny_unknown_tools: bool = True
    deny_unknown_llm_profiles: bool = True
    require_memory_scope: bool = True
    allow_memory_writes: bool = False


class PolicyConfig(StrictConfigModel):
    default_profile: str = "default"
    profiles: dict[str, PolicyProfileConfig]


class ObservabilityConfig(StrictConfigModel):
    log_level: str = "INFO"
    structured_logging: bool = True
    trace_payloads_enabled: bool = True
    redact_secrets: bool = True


class HealthConfig(StrictConfigModel):
    expose_config_summary: bool = True
    expose_provider_names: bool = True
    expose_secret_values: bool = False


class BackendConfig(StrictConfigModel):
    app: AppConfig
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    usecases: dict[str, UseCaseConfig]
    strategies: dict[str, StrategyConfig]
    agents: dict[str, AgentConfig]
    llm: LLMConfig
    mcp: MCPConfig
    persistence: PersistenceConfig
    policy: PolicyConfig
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
```

This sketch is intentionally not the final production implementation. It defines the intended validation boundary and cross-reference structure.

---

## 14. Cross-Reference Validation Rules

Schema validation should check both field types and cross-references.

Required cross-reference checks:

| Rule | Example Failure |
|---|---|
| `app.active_usecase` exists in `usecases` | `default_chat` is configured but not defined. |
| Active use case is enabled | `default_chat.enabled=false`. |
| Use-case `strategy` exists and is enabled | `router` missing or disabled. |
| Use-case `default_agent` exists and is enabled | `support_agent` missing or disabled. |
| Every `allowed_agents` entry exists | `document_qa_agent` listed but not configured. |
| Use-case `orchestrator_llm_profile` exists if set | `local_reasoning` missing. |
| Strategy `llm_profile` exists if set | Router uses unknown profile. |
| Agent `llm_profile` exists if set | Agent references unknown model profile. |
| `llm.default_profile` exists | Default profile is missing. |
| Every LLM profile references an existing provider | Profile uses missing provider. |
| Every fallback profile exists | Fallback references unknown profile. |
| LLM fallback graph has no cycles | `a -> b -> a`. |
| Policy default profile exists | `policy.default_profile` missing. |
| Use-case policy profile exists | Use case references missing policy profile. |
| Agent tools are a subset of use-case tools when both are configured | Agent can call a tool not allowed by use case. |
| V1 has one MCP main endpoint | Multiple active MCP servers are configured. |
| SQLite stores have a path when provider is `sqlite` | Missing `workflow_state.path`. |
| `memory_store` memory provider has required adapter config | Missing memory database path or required scope config. |

### 14.1 Validation Order

Recommended order:

```text
1. Read YAML.
2. Merge optional override YAML.
3. Resolve environment variables.
4. Parse into Pydantic schema.
5. Run cross-reference validation.
6. Run secret-safety validation.
7. Return immutable ConfigurationView.
```

---

## 15. Secret-Safety Validation

The configuration loader should prevent common secret mistakes.

### 15.1 Recommended Rules

Fail startup when:

- A likely secret key is present as a non-empty literal value in checked-in YAML, unless explicitly allowed for local-only dummy values.
- A required secret environment variable is missing.
- Redaction is disabled outside test mode.
- `health.expose_secret_values` is true outside a test fixture.

Warn, but do not necessarily fail, when:

- Optional provider API key is empty for a provider that is not used by any active profile.
- A provider is configured but no profile references it.
- A profile is configured but no use case, strategy, or agent references it.

### 15.2 Secret Redaction Utility

`app/config/redaction.py` should provide a reusable redaction function:

```python
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
)


def redact_config(value: object) -> object:
    """Return a copy of a config structure with sensitive values redacted."""
    ...
```

This utility should be used by logs, health summaries, error formatting, and tests.

---

## 16. Configuration View Implementation

The contracts phase defines a `ConfigurationView` protocol. This phase should implement a concrete read-only view.

Recommended implementation:

```python
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from app.contracts.errors import ConfigurationError


class ValidatedConfigurationView:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = _freeze(values)

    def get(self, path: str, default: Any = None) -> Any:
        current: Any = self._values
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return default
            current = current[part]
        return current

    def require(self, path: str) -> Any:
        value = self.get(path, None)
        if value is None:
            raise ConfigurationError(f"Missing required config path: {path}")
        return value

    def section(self, path: str) -> dict[str, Any]:
        value = self.require(path)
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"Config path is not a section: {path}")
        return dict(value)

    def as_redacted_dict(self) -> dict[str, Any]:
        return redact_config(_unfreeze(self._values))


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
```

### 16.1 Access Pattern

Runtime modules should use simple path access for broad configuration:

```python
active_usecase = config.require("app.active_usecase")
llm_default_profile = config.require("llm.default_profile")
```

Modules that need typed configuration can use resolver helpers:

```python
profile = llm_profile_resolver.resolve("local_reasoning")
agent_config = agent_config_resolver.resolve("support_agent")
```

Avoid passing raw nested dictionaries deep into agents.

---

## 17. Configuration Loader Implementation

Recommended concrete loader:

```python
from pathlib import Path

import yaml

from app.contracts.config import ConfigurationLoader
from app.config.env_resolver import resolve_env_refs
from app.config.schemas import BackendConfig
from app.config.validation import validate_cross_references
from app.config.view import ValidatedConfigurationView


class YamlConfigurationLoader(ConfigurationLoader):
    def __init__(
        self,
        config_path: Path,
        override_path: Path | None = None,
    ) -> None:
        self.config_path = config_path
        self.override_path = override_path

    async def load(self) -> ValidatedConfigurationView:
        raw = _read_yaml(self.config_path)

        if self.override_path and self.override_path.exists():
            override = _read_yaml(self.override_path)
            raw = _deep_merge(raw, override)

        resolved = resolve_env_refs(raw)
        parsed = BackendConfig.model_validate(resolved)
        validate_cross_references(parsed)

        values = parsed.model_dump(mode="python")
        return ValidatedConfigurationView(values)
```

### 17.1 Deep Merge Rules

For optional override YAML:

- Dictionaries merge recursively.
- Scalars replace scalars.
- Lists replace lists by default.
- `null` can explicitly clear optional values only where schema allows it.
- Overrides should never silently create unknown fields because schema validation uses `extra="forbid"`.

This keeps local/test overrides deterministic.

---

## 18. Settings Model

`settings.py` should handle process-level settings before YAML loads.

Recommended settings:

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    env: str = "local"
    config_path: Path = Path("./config/app.yaml")
    config_override_path: Path | None = None
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
```

### 18.1 Settings vs YAML

Use settings for:

- Config file paths.
- Application environment name.
- Data directory default.
- Process-level local startup behavior.

Use YAML for:

- Use cases.
- Agents.
- Strategies.
- LLM providers and profiles.
- MCP endpoint.
- Persistence providers.
- Policy profiles.
- Observability behavior.

---

## 19. Bootstrap and Composition Root Integration

The configuration phase should produce a bootstrap function that the application factory can call.

Recommended location:

```text
app/config/bootstrap.py
```

Example:

```python
from app.config.loader import YamlConfigurationLoader
from app.config.settings import Settings


async def load_backend_config(settings: Settings) -> ValidatedConfigurationView:
    loader = YamlConfigurationLoader(
        config_path=settings.config_path,
        override_path=settings.config_override_path,
    )
    return await loader.load()
```

Composition root usage:

```python
async def build_app() -> FastAPI:
    settings = load_settings()
    config = await load_backend_config(settings)

    trace_store = build_trace_store(config)
    workflow_state = build_workflow_state_store(config)
    memory = build_memory_gateway(config)
    policy = build_policy_service(config)
    llm = build_llm_gateway(config, policy, trace_store)
    tools = build_tool_gateway(config, policy, trace_store)
    agents = build_agent_registry(config)
    strategies = build_strategy_registry(config)

    orchestrator = OrchestrationRuntime(
        config=config,
        llm=llm,
        memory=memory,
        state=workflow_state,
        tools=tools,
        trace=trace_store,
        policy=policy,
        agents=agents,
        strategies=strategies,
    )
```

The composition root is allowed to know concrete implementations. Agents, strategies, API routes, and provider adapters should not become mini-composition roots.

---

## 20. Use-Case Configuration Design

Use cases define the runtime behavior available to a frontend/API request.

A use case should answer:

- Which strategy should handle this request?
- Which agents are allowed?
- Which agent is the default?
- Which LLM profile can the orchestrator use?
- Is memory enabled for this use case?
- Are tools enabled for this use case?
- Which tools are allowed?
- Which policy profile applies?

Example:

```yaml
usecases:
  document_qa:
    enabled: true
    description: Ask questions over project documents and memory.
    strategy: router
    default_agent: document_qa_agent
    allowed_agents:
      - document_qa_agent
      - reviewer_agent
    orchestrator_llm_profile: local_reasoning
    memory:
      enabled: true
      include_document_chunks: true
      default_limit: 10
    tools:
      enabled: true
      allowed_tools:
        - documents.search
        - documents.get_chunk
    policy_profile: document_qa_policy
```

### 20.1 Use-Case Selection

Selection order:

```text
1. Explicit usecase from RequestContext, if provided and allowed.
2. Configured app.active_usecase.
3. Fail with ConfigurationError.
```

The API/session layer may pass a requested use case, but orchestration should validate that it exists and is enabled.

---

## 21. Strategy Configuration Design

Strategies define orchestration behavior.

Recommended strategy types:

| Type | Purpose |
|---|---|
| `direct` | Run the default configured agent. |
| `router` | Use an orchestrator LLM profile to select an agent. |
| `sequential` | Run a defined sequence of agents. |

Example:

```yaml
strategies:
  direct_agent:
    enabled: true
    type: direct
    description: Run the use-case default agent.

  router:
    enabled: true
    type: router
    description: Route requests to the best allowed agent.
    llm_profile: local_reasoning
    max_candidate_agents: 3

  review_then_answer:
    enabled: false
    type: sequential
    sequence:
      - document_qa_agent
      - reviewer_agent
```

### 21.1 Strategy Resolution Rule

A strategy should never hard-code LLM model names. It may request:

```text
strategy.llm_profile
usecase.orchestrator_llm_profile
llm.default_profile
```

The LLM gateway or profile resolver handles provider/model details.

---

## 22. Agent Configuration Design

Agent configuration defines registration, capabilities, LLM profile, memory permissions, prompt references, and tool allowlists.

Example:

```yaml
agents:
  document_qa_agent:
    enabled: true
    module: app.agents.document_qa_agent
    class_name: DocumentQaAgent
    description: Answers questions using memory and document chunks.
    capabilities:
      - document_qa
      - citation_generation
    llm_profile: research_reasoning
    allowed_tools:
      - documents.search
      - documents.get_chunk
    memory:
      search_enabled: true
      write_enabled: false
    prompts:
      system_prompt: prompts/document_qa/system.md
      developer_prompt: prompts/document_qa/developer.md
```

### 22.1 Agent Configuration Rules

Agents may read their configuration through `context.config` or a future typed `AgentConfigResolver`.

Agents must not:

- Read raw environment variables.
- Parse YAML.
- Hard-code provider/model names.
- Hard-code MCP URLs.
- Hard-code database paths.
- Grant themselves tools not configured for the use case.

---

## 23. LLM Provider and Profile Configuration

LLM configuration is split into providers and profiles.

### 23.1 Provider Config

A provider describes how to reach a runtime or API.

```yaml
llm:
  providers:
    local_openai_compatible:
      type: openai_compatible
      base_url: ${env:LOCAL_LLM_BASE_URL}
      api_key: ${env:LOCAL_LLM_API_KEY:}
      timeout_seconds: 90

    openai:
      type: openai
      api_key: ${env:OPENAI_API_KEY}
      timeout_seconds: 60
```

### 23.2 Profile Config

A profile describes a logical model use.

```yaml
llm:
  default_profile: local_reasoning
  profiles:
    local_reasoning:
      provider: local_openai_compatible
      model: qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1
      temperature: 0.7
      max_tokens: 2048
      timeout_seconds: 90
      fallback_profiles: []

    research_reasoning:
      provider: local_openai_compatible
      model: qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1
      temperature: 0.2
      max_tokens: 4096
      fallback_profiles:
        - local_reasoning
```

### 23.3 LLM Profile Resolution Order

Later `llm-gateway-architecture.md` should implement profile resolution in this order:

```text
1. Explicit profile requested by strategy or agent, if policy allows it.
2. Agent-specific llm_profile from YAML.
3. Strategy-specific llm_profile from YAML.
4. Use-case orchestrator_llm_profile or use-case default profile.
5. Application llm.default_profile.
6. Fail with ConfigurationError.
```

### 23.4 Local OpenAI-Compatible Endpoint Support

The config shape should support local runtimes that expose `/v1/chat/completions` through an OpenAI-compatible API.

Example provider:

```yaml
llm:
  providers:
    local_openai_compatible:
      type: openai_compatible
      base_url: ${env:LOCAL_LLM_BASE_URL:http://192.168.1.80:8081/v1}
      api_key: ${env:LOCAL_LLM_API_KEY:}
      timeout_seconds: 90
```

Agents should still reference only:

```yaml
llm_profile: local_reasoning
```

They should not know the URL, provider type, model string, or API key.

---

## 24. MCP Configuration

V1 uses one MCP endpoint.

Recommended YAML:

```yaml
mcp:
  main:
    url: ${env:MCP_MAIN_URL:http://localhost:9001/mcp}
    timeout_seconds: 30
    tool_discovery_enabled: true
```

### 24.1 MCP Rules

- The backend config names one main MCP endpoint.
- Domain separation is handled through tool names, agent allowlists, use-case allowlists, and policy.
- The backend does not contain MCP server implementation code.
- The tool gateway and MCP client adapter consume this configuration.
- Agents never read `mcp.main.url` directly.

---

## 25. Persistence Configuration

Persistence configuration defines which adapters should be built by the composition root.

Recommended YAML:

```yaml
persistence:
  workflow_state:
    provider: sqlite
    path: ${env:APP_DATA_DIR:./data}/workflow_state.db

  trace:
    provider: sqlite
    path: ${env:APP_DATA_DIR:./data}/trace.db

  memory:
    provider: memory_store
    config:
      database_path: ${env:MEMORY_STORE_DB_PATH:./data/memory}
      default_scope: project
```

### 25.1 Persistence Rules

- `workflow_state.provider=sqlite` builds a future `SqliteWorkflowStateStore`.
- `trace.provider=sqlite` builds a future `SqliteTraceStore`.
- `memory.provider=memory_store` builds a future `MemoryStoreAdapter` that wraps `memory_store.service.MemoryService`.
- ArcadeDB configuration remains behind `memory_store` and the memory adapter.
- Agents and strategies do not read database paths.

---

## 26. Policy Configuration

The configuration phase should define policy profile shape, not a full policy engine.

Recommended YAML:

```yaml
policy:
  default_profile: default
  profiles:
    default:
      deny_unknown_tools: true
      deny_unknown_llm_profiles: true
      require_memory_scope: true
      allow_memory_writes: false

    document_qa_policy:
      deny_unknown_tools: true
      deny_unknown_llm_profiles: true
      require_memory_scope: true
      allow_memory_writes: false
```

### 26.1 Policy Defaults

Recommended V1 defaults:

```text
Deny unknown tools.
Deny unknown LLM profiles.
Require memory scope.
Trace all LLM calls.
Trace all tool calls.
Allow tools per agent and use case, not globally.
Allow LLM profiles per agent/use case, not globally.
Memory writes disabled unless explicitly enabled.
```

Detailed policy logic belongs in `policy-architecture.md`.

---

## 27. Observability and Health Configuration

Configuration should allow observability defaults without implementing the full observability layer yet.

Recommended YAML:

```yaml
observability:
  log_level: ${env:APP_LOG_LEVEL:INFO}
  structured_logging: true
  trace_payloads_enabled: true
  redact_secrets: true

health:
  expose_config_summary: true
  expose_provider_names: true
  expose_secret_values: false
```

### 27.1 Safe Health Summary

A safe health/config summary may include:

```json
{
  "configured": true,
  "environment": "local",
  "active_usecase": "default_chat",
  "llm_profiles_count": 2,
  "llm_providers": ["local_openai_compatible"],
  "mcp_configured": true,
  "workflow_state_provider": "sqlite",
  "trace_provider": "sqlite",
  "memory_provider": "memory_store"
}
```

It must not include:

- API keys.
- Tokens.
- Full authorization headers.
- Passwords.
- Sensitive connection strings.
- Raw prompts.
- Raw LLM completions.
- Memory contents.

---

## 28. Feature Flags

Feature flags are coarse runtime switches for the walking skeleton and local development.

Recommended YAML:

```yaml
features:
  streaming_enabled: true
  memory_enabled: true
  tools_enabled: true
  trace_enabled: true
```

### 28.1 Feature Flag Rules

- Feature flags should not replace policy.
- Feature flags should not grant permissions.
- Disabling a feature should make dependent modules fail safely or use fakes in tests.
- Production behavior should not depend on hidden, undocumented flags.

---

## 29. Prompt Reference Configuration

Prompts may be referenced in agent configuration, but this phase should not build a full prompt-management system.

Recommended YAML:

```yaml
agents:
  support_agent:
    prompts:
      system_prompt: prompts/support_agent/system.md
      developer_prompt: prompts/support_agent/developer.md
```

Rules:

- Prompt paths should be relative to a configured prompt root or project root.
- Missing prompt files should fail startup only for enabled agents that require them.
- Prompt files should not contain secrets.
- Prompt loading should be implemented later with agent architecture or prompt architecture if needed.

---

## 30. Configuration Access Helpers

The raw `ConfigurationView` supports simple path reads. Later modules will benefit from small resolver helpers.

Recommended helpers:

```text
UseCaseConfigResolver
AgentConfigResolver
StrategyConfigResolver
LLMProfileResolver
ToolPermissionConfigResolver
PersistenceConfigResolver
PolicyProfileResolver
```

### 30.1 Resolver Responsibility

Resolvers should:

- Accept a `ConfigurationView`.
- Return small typed objects or dictionaries for one concern.
- Hide nested path details from runtime modules.
- Raise `ConfigurationError` with trace-safe messages.
- Not instantiate provider SDKs or database clients.

Example:

```python
class LLMProfileResolver:
    def __init__(self, config: ConfigurationView) -> None:
        self.config = config

    def resolve(self, profile_name: str | None) -> dict[str, Any]:
        name = profile_name or self.config.require("llm.default_profile")
        profiles = self.config.section("llm.profiles")
        if name not in profiles:
            raise ConfigurationError(f"Unknown LLM profile: {name}")
        return profiles[name]
```

The real `llm-gateway-architecture.md` can refine this into stronger types.

---

## 31. Startup Behavior

Startup should fail fast when configuration is invalid.

Recommended startup sequence:

```text
1. Load process settings.
2. Initialize minimal console logging.
3. Load base YAML and optional override YAML.
4. Resolve environment variable references.
5. Validate schema.
6. Validate cross-references.
7. Redact and log safe configuration summary.
8. Build concrete services in composition root.
9. Register routes.
10. Start backend.
```

### 31.1 Failure Behavior

For `ConfigurationError` during startup:

- Log a concise, redacted error summary.
- Include the failing config path where safe.
- Do not print secret values.
- Stop application startup.
- In tests, raise the exception directly.

---

## 32. Test Strategy

The configuration phase should have strong unit coverage before concrete modules are implemented.

### 32.1 Required Unit Tests

| Test | Purpose |
|---|---|
| Load valid minimal config | Proves loader works with the smallest supported config. |
| Load valid full config | Proves all sections parse and validate. |
| Missing active use case fails | Proves cross-reference validation. |
| Unknown strategy fails | Prevents runtime strategy lookup errors. |
| Unknown default agent fails | Prevents orchestration startup failures. |
| Unknown LLM provider fails | Prevents gateway runtime failure. |
| Unknown LLM fallback fails | Prevents fallback runtime failure. |
| Fallback cycle fails | Prevents infinite fallback loops. |
| Missing required env var fails | Proves env resolver behavior. |
| Optional env default resolves | Proves local/test ergonomics. |
| Secret redaction works | Prevents accidental log leaks. |
| `ConfigurationView.require` raises cleanly | Proves runtime access behavior. |
| Override YAML deep merge works | Proves deterministic local/test overrides. |

### 32.2 Example Test Fixtures

```text
tests/fixtures/config/valid_minimal.yaml
tests/fixtures/config/valid_full.yaml
tests/fixtures/config/invalid_unknown_llm_profile.yaml
tests/fixtures/config/invalid_unknown_agent.yaml
tests/fixtures/config/invalid_missing_env.yaml
```

### 32.3 Fake Config Use

Contract tests can continue using `FakeConfigurationView`. Configuration loader tests should use `YamlConfigurationLoader`.

This keeps contract tests fast while validating the real loader separately.

---

## 33. Recommended Implementation Order Inside This Phase

### Step 1: Add Settings Model

Deliverables:

- `app/config/settings.py`
- `.env.example`
- Unit tests for defaults and env overrides

Success criteria:

- Settings load without YAML.
- Local paths are predictable.

### Step 2: Add YAML Loader Skeleton

Deliverables:

- `app/config/loader.py`
- Basic YAML read function
- Loader unit test with a minimal YAML file

Success criteria:

- YAML can be read from a configured path.
- Missing file produces a useful `ConfigurationError`.

### Step 3: Add Environment Resolver

Deliverables:

- `app/config/env_resolver.py`
- Tests for required and optional env refs

Success criteria:

- `${env:VAR}` and `${env:VAR:default}` resolve correctly.
- Missing required env vars fail fast.
- Secret values are not leaked in errors.

### Step 4: Add Schema Models

Deliverables:

- `app/config/schemas.py`
- Pydantic model groups
- Valid minimal and valid full test fixtures

Success criteria:

- Valid configs parse.
- Unknown fields fail.
- Invalid types fail with useful messages.

### Step 5: Add Cross-Reference Validation

Deliverables:

- `app/config/validation.py`
- Tests for unknown use case, strategy, agent, LLM profile, provider, policy profile, and fallback cycle

Success criteria:

- Invalid references fail before backend startup completes.

### Step 6: Add Redaction Utility

Deliverables:

- `app/config/redaction.py`
- Tests for nested dictionaries and lists

Success criteria:

- Sensitive values are consistently redacted.

### Step 7: Add Validated Configuration View

Deliverables:

- `app/config/view.py`
- Tests for `get`, `require`, `section`, immutability, and redacted dump

Success criteria:

- Runtime modules can use the `ConfigurationView` protocol.
- Loaded config is read-only by convention or enforcement.

### Step 8: Add Bootstrap Integration

Deliverables:

- `app/config/bootstrap.py`
- Application factory integration
- Health summary stub integration

Success criteria:

- Backend startup loads validated config.
- Safe config summary is available to health route.

---

## 34. Walking Skeleton Enabled by Configuration

After this phase, the backend should be ready for a configuration-backed walking skeleton:

```text
Startup
  -> load settings
  -> load YAML
  -> resolve env vars
  -> validate schema
  -> validate references
  -> create ConfigurationView
  -> build fake or stub services from config

POST /chat future phase
  -> SessionService
  -> OrchestrationRuntime
  -> resolve active use case from config
  -> resolve strategy from config
  -> resolve agent from config
  -> resolve LLM profile name from config
  -> execute fake/stub runtime path
```

The important outcome is not model intelligence yet. The important outcome is that behavior is selected by configuration and invalid wiring fails before runtime.

---

## 35. Acceptance Criteria

This architecture is complete when:

- The backend has a concrete YAML configuration loader.
- The loader implements the existing `ConfigurationLoader` contract.
- The loaded config is exposed through the existing `ConfigurationView` contract.
- Environment variable references are resolved before schema validation.
- Required environment variables fail fast when missing.
- Optional environment variables can use explicit defaults.
- Pydantic or equivalent schema validation rejects unknown fields and invalid types.
- Cross-reference validation catches missing use cases, strategies, agents, providers, profiles, fallback profiles, and policy profiles.
- Fallback profile cycles are rejected.
- Secrets are redacted from logs, health summaries, validation messages, and config dumps.
- Provider/model details live in YAML and environment variables, not agents or API routes.
- Agents reference logical `llm_profile` names only.
- The configuration supports local OpenAI-compatible LLM endpoints.
- The configuration supports one V1 MCP endpoint through `mcp.main.url`.
- Persistence configuration can build future SQLite workflow state, SQLite trace, and `memory_store` memory adapters.
- Policy configuration can define deny-by-default settings for tools, LLM profiles, and memory behavior.
- Unit tests can load valid config fixtures and reject invalid fixtures.
- The backend is ready for the next document: `observability-architecture.md`.

---

## 36. Anti-Patterns to Avoid

Avoid these during the configuration phase:

- Letting agents read `os.environ`.
- Letting agents parse YAML.
- Hard-coding provider URLs in agents.
- Hard-coding model names in agents.
- Hard-coding MCP URLs in tool-calling code outside the MCP client adapter builder.
- Allowing raw nested dictionaries to spread everywhere without resolver helpers.
- Allowing unknown config keys silently.
- Committing real API keys in YAML.
- Printing full config with secrets during startup.
- Returning secrets in health responses.
- Making feature flags act like authorization.
- Supporting multiple MCP endpoints in V1 without a concrete need.
- Adding hot reload before the basic loader is stable.
- Adding provider SDK imports into config schemas.
- Creating circular dependencies between config, orchestration, agents, and gateways.

---

## 37. Future Documents That Depend on Configuration

| Future Document | Configuration Dependency |
|---|---|
| `observability-architecture.md` | Uses `observability`, `health`, redaction rules, log level, trace payload settings. |
| `persistence-architecture.md` | Uses `persistence.workflow_state`, `persistence.trace`, and `persistence.memory`. |
| `sqlite-workflow-state-architecture.md` | Uses SQLite workflow state provider and path config. |
| `sqlite-trace-store-architecture.md` | Uses SQLite trace provider and path config. |
| `backend-api-architecture.md` | Uses active use case, feature flags, health config, and request-level use-case validation. |
| `session-service-architecture.md` | Uses workflow state provider and session defaults. |
| `llm-gateway-architecture.md` | Uses LLM providers, profiles, fallback profiles, timeouts, and policy profile names. |
| `memory-store-adapter-architecture.md` | Uses memory provider config and scope defaults. |
| `tooling-mcp-client-architecture.md` | Uses single MCP endpoint and tool allowlists. |
| `orchestration-architecture.md` | Uses use-case, strategy, agent, orchestrator LLM profile, and feature flag config. |
| `workflow-strategies-architecture.md` | Uses strategy type and strategy-specific configuration. |
| `agents-architecture.md` | Uses agent module/class, capability, LLM profile, prompt, memory, and tool config. |
| `policy-architecture.md` | Uses policy profiles and deny-by-default config. |
| `deployment-architecture.md` | Uses environment variables, config paths, data paths, and provider secrets pattern. |

---

## 38. Summary

The configuration layer is the runtime wiring backbone for the backend application.

It should be implemented immediately after the core contracts because every later concrete module needs validated, provider-neutral configuration. The loader should resolve environment variables, validate YAML schema, validate cross-references, protect secrets, and return a read-only `ConfigurationView` that runtime modules can safely depend on.

The most important implementation rule is:

> **Configuration selects behavior; contracts define capabilities; concrete modules implement those capabilities. Agents and API routes should not hard-code provider, model, MCP, storage, or policy details.**
