"""Concrete backend-owned tool gateway built over registry, policy, and MCP adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.config.view import ToolingSettings
from app.contracts.context import OrchestrationContext
from app.contracts.policy import PolicyAction, PolicyDecision
from app.contracts.tools import (
    ToolCallRequest,
    ToolCapabilitiesResult,
    ToolCapabilitySummary,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealthResult,
    ToolListFilters,
    ToolListResult,
    ToolResult,
    ToolScopes,
    ToolStreamEvent,
)
from app.contracts.trace import TOOL_CALL_COMPLETED, TOOL_CALL_FAILED, TOOL_CALL_STARTED, TraceEvent
from app.tools.errors import (
    ToolArgumentValidationError,
    ToolCancelledError,
    ToolDisabledError,
    ToolGatewayError,
    ToolNotFoundError,
    ToolPolicyApprovalRequiredError,
    ToolPolicyDeniedError,
)
from app.tools.mcp.fake import FakeMCPClientAdapter
from app.tools.mcp.protocol_models import MCPClientAdapter, MCPToolCallRequest
from app.tools.models import AdapterRequestMetadata, ResolvedToolDefinition, ToolRegistryEntry
from app.tools.redaction import redact_tool_payload
from app.tools.registry import ToolRegistry
from app.tools.result_normalizer import ToolResultNormalizer
from app.tools.retry import (
    is_retryable_error,
    normalize_runtime_error,
    result_retry_error,
    retry_attempts_for_request,
)
from app.tools.schema_validation import ToolArgumentValidator
from app.policy.tool_policy import build_tool_policy_request


class DefaultToolGateway:
    """Provider-neutral tool gateway that owns policy, validation, and safe traces."""

    def __init__(
        self,
        *,
        settings: ToolingSettings,
        registry: ToolRegistry,
        argument_validator: ToolArgumentValidator,
        result_normalizer: ToolResultNormalizer,
        mcp_adapter: MCPClientAdapter,
        component: str = "app.tools.gateway",
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._argument_validator = argument_validator
        self._result_normalizer = result_normalizer
        self._mcp_adapter = mcp_adapter
        self._component = component

    async def list_tools(
        self,
        context: OrchestrationContext,
        filters: ToolListFilters | None = None,
    ) -> ToolListResult:
        if not self._settings.enabled:
            return ToolListResult(tools=[], metadata={"tooling_enabled": False})

        visible_tools: list[ToolDefinition] = []
        for tool in self._registry.list(filters):
            entry = self._registry.resolve_entry(tool.name)
            decision = await self._evaluate_policy(
                action="tool.list",
                tool_name=tool.name,
                context=context,
                scopes=self._effective_scopes(ToolScopes(), context),
                definition=entry.definition,
            )
            if decision.allowed:
                visible_tools.append(tool)

        return ToolListResult(
            tools=visible_tools,
            metadata={
                "tooling_enabled": True,
                "total_visible": len(visible_tools),
            },
        )

    async def get_tool(
        self,
        tool_name: str,
        context: OrchestrationContext,
    ) -> ToolDefinition | None:
        if not self._settings.enabled:
            return None

        try:
            entry = self._registry.resolve_entry(tool_name)
        except ToolNotFoundError:
            return None

        decision = await self._evaluate_policy(
            action="tool.get",
            tool_name=tool_name,
            context=context,
            scopes=self._effective_scopes(ToolScopes(), context),
            definition=entry.definition,
        )
        if not decision.allowed:
            return None
        return _to_public_definition(entry)

    async def execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> ToolExecutionResult:
        return await self._execute_internal(
            request=request,
            context=context,
            action="tool.execute",
        )

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolResult:
        return await self._execute_internal(
            request=request,
            context=context,
            action="tool.call",
        )

    async def stream_execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[ToolStreamEvent]:
        scopes = self._effective_scopes(request.scopes, context)
        if not self._settings.enabled:
            disabled_error = ToolDisabledError("Tooling is disabled by configuration.")
            await self._record_failure_event(
                context=context,
                tool_name=request.tool_name,
                scopes=scopes,
                error=disabled_error,
                attempt_count=0,
                duration_ms=None,
            )
            raise disabled_error

        try:
            entry, arguments, timeout_seconds = await self._prepare_execution(
                request=request,
                context=context,
                action="tool.stream_execute",
                scopes=scopes,
                require_streaming=True,
            )
        except ToolGatewayError as exc:
            await self._record_failure_event(
                context=context,
                tool_name=request.tool_name,
                scopes=scopes,
                error=exc,
                attempt_count=0,
                duration_ms=None,
            )
            raise

        attempts = retry_attempts_for_request(
            definition=entry.definition,
            default_max_retries=self._settings.defaults.max_retries,
            idempotency_key=request.idempotency_key,
        )

        for attempt_count in range(1, attempts + 1):
            started_at = perf_counter()
            await self._record_started_event(
                context=context,
                tool_name=entry.logical_name,
                scopes=scopes,
                stream=True,
                timeout_seconds=timeout_seconds,
                request=request,
                arguments=arguments,
                attempt_count=attempt_count,
            )
            adapter_request = self._build_adapter_request(
                entry=entry,
                arguments=arguments,
                request=request,
                timeout_seconds=timeout_seconds,
                scopes=scopes,
                context=context,
            )

            saw_event = False
            try:
                async for raw_event in self._mcp_adapter.stream_tool(request=adapter_request):
                    duration_ms = self._duration_ms(started_at)
                    normalized = self._result_normalizer.normalize_stream_event(
                        entry.definition,
                        raw_event,
                        duration_ms=duration_ms if raw_event.type == "completed" else None,
                    )
                    saw_event = True

                    if raw_event.type == "completed":
                        result = normalized.result or ToolExecutionResult(
                            tool_name=entry.logical_name,
                            status="completed",
                        )
                        await self._record_completed_event(
                            context=context,
                            result=result,
                            scopes=scopes,
                            attempt_count=attempt_count,
                            duration_ms=duration_ms,
                        )
                        yield normalized
                        return

                    if raw_event.type == "cancelled":
                        cancelled_error = ToolCancelledError("Tool execution was cancelled.")
                        await self._record_failure_event(
                            context=context,
                            tool_name=entry.logical_name,
                            scopes=scopes,
                            error=cancelled_error,
                            attempt_count=attempt_count,
                            duration_ms=duration_ms,
                            status="cancelled",
                        )
                        yield normalized
                        return

                    if raw_event.type == "error":
                        stream_error = ToolGatewayError(
                            normalized.error.message
                            if normalized.error is not None
                            else "Tool stream failed."
                        )
                        await self._record_failure_event(
                            context=context,
                            tool_name=entry.logical_name,
                            scopes=scopes,
                            error=stream_error,
                            attempt_count=attempt_count,
                            duration_ms=duration_ms,
                        )
                        yield normalized
                        return

                    yield normalized
            except BaseException as exc:
                runtime_error = normalize_runtime_error(exc, streaming=True)
                if (
                    attempt_count < attempts
                    and not saw_event
                    and is_retryable_error(
                        runtime_error,
                        definition=entry.definition,
                        idempotency_key=request.idempotency_key,
                    )
                ):
                    continue

                await self._record_failure_event(
                    context=context,
                    tool_name=entry.logical_name,
                    scopes=scopes,
                    error=runtime_error,
                    attempt_count=attempt_count,
                    duration_ms=self._duration_ms(started_at),
                    status=(
                        "cancelled"
                        if isinstance(runtime_error, ToolCancelledError)
                        else "failed"
                    ),
                )
                raise runtime_error

            missing_event_error = ToolGatewayError(
                "Tool stream ended without a terminal event."
            )
            await self._record_failure_event(
                context=context,
                tool_name=entry.logical_name,
                scopes=scopes,
                error=missing_event_error,
                attempt_count=attempt_count,
                duration_ms=self._duration_ms(started_at),
            )
            raise missing_event_error

        raise RuntimeError("Tool streaming attempts exhausted without a terminal event.")

    async def health(self) -> ToolHealthResult:
        snapshot = self._registry.discovery_snapshot
        mcp_configured = bool(self._settings.mcp_server.endpoint)
        auth_mode: str = self._settings.mcp_server.auth.mode
        adapter_error: str | None = None
        mcp_status = "disabled" if not self._settings.enabled else "not_checked"
        discovery_state = "disabled" if not self._settings.enabled else "pending"
        tools_discovered: int | None = None
        adapter_is_fake = isinstance(self._mcp_adapter, FakeMCPClientAdapter)

        if not self._settings.enabled:
            discovery_state = "disabled"
            tools_discovered = 0
        elif not mcp_configured:
            mcp_status = "not_configured"
            discovery_state = (
                "disabled" if not self._settings.mcp_server.tool_discovery_enabled else "pending"
            )
        elif snapshot is not None and snapshot.error:
            mcp_status = "error"
            discovery_state = "error"
            adapter_error = snapshot.error
            tools_discovered = snapshot.tool_count if snapshot.discovered_at is not None else 0
        elif snapshot is not None and snapshot.discovered_at is not None:
            mcp_status = "ok"
            discovery_state = "ok"
            tools_discovered = snapshot.tool_count
        elif adapter_is_fake:
            try:
                adapter_health = await self._mcp_adapter.health()
            except Exception as exc:
                mcp_status = "error"
                discovery_state = "error"
                adapter_error = type(exc).__name__
                tools_discovered = 0
            else:
                mcp_status = adapter_health.status
                auth_mode = adapter_health.auth_mode
                adapter_error = adapter_health.error
                discovery_state = "ok" if adapter_health.status == "ok" else "error"
                tools_discovered = adapter_health.tool_count
        else:
            mcp_status = "not_checked"
            discovery_state = (
                "disabled" if not self._settings.mcp_server.tool_discovery_enabled else "pending"
            )

        registry_status = "disabled" if not self._settings.enabled else "ok"
        if snapshot is not None and snapshot.error:
            registry_status = "degraded"
        elif adapter_error is not None and self._settings.enabled:
            registry_status = "degraded"

        status = "disabled"
        if self._settings.enabled:
            status = "ok"
            if not mcp_configured:
                status = "not_configured"
            elif mcp_status == "error" or registry_status == "degraded":
                status = "degraded"

        entries = self._registry.entries
        return ToolHealthResult(
            status=status,
            tooling_enabled=self._settings.enabled,
            mcp_configured=mcp_configured,
            mcp_status=mcp_status,
            tools_configured=len(self._registry.configured_entries),
            tools_discovered=tools_discovered,
            tools_enabled=sum(1 for entry in entries.values() if entry.definition.enabled),
            registry_status=registry_status,
            error=adapter_error,
            metadata={
                "server_name": self._settings.mcp_server.name,
                "transport": self._settings.mcp_server.transport,
                "auth_mode": auth_mode,
                "discovery_enabled": self._settings.mcp_server.tool_discovery_enabled,
                "discovery_state": discovery_state,
            },
        )

    async def capabilities(self) -> ToolCapabilitiesResult:
        enabled_tools = []
        for entry in self._registry.entries.values():
            if not entry.definition.enabled:
                continue
            enabled_tools.append(
                ToolCapabilitySummary(
                    name=entry.logical_name,
                    display_name=entry.definition.description,
                    safety_level=entry.definition.safety_level,
                    enabled=True,
                    supports_streaming=entry.definition.supports_streaming,
                    approval_required=entry.definition.approval_required,
                    tags=entry.definition.tags,
                    metadata={},
                )
            )

        return ToolCapabilitiesResult(
            enabled=self._settings.enabled,
            mcp_configured=bool(self._settings.mcp_server.endpoint),
            streaming_supported=any(tool.supports_streaming for tool in enabled_tools),
            available_logical_tools=enabled_tools if self._settings.enabled else [],
            metadata={
                "server_name": self._settings.mcp_server.name,
                "transport": self._settings.mcp_server.transport,
                "discovery_enabled": self._settings.mcp_server.tool_discovery_enabled,
            },
        )

    async def _execute_internal(
        self,
        *,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
        action: PolicyAction,
    ) -> ToolExecutionResult:
        scopes = self._effective_scopes(request.scopes, context)
        if not self._settings.enabled:
            disabled_error = ToolDisabledError("Tooling is disabled by configuration.")
            await self._record_failure_event(
                context=context,
                tool_name=request.tool_name,
                scopes=scopes,
                error=disabled_error,
                attempt_count=0,
                duration_ms=None,
            )
            raise disabled_error

        try:
            entry, arguments, timeout_seconds = await self._prepare_execution(
                request=request,
                context=context,
                action=action,
                scopes=scopes,
                require_streaming=False,
            )
        except ToolGatewayError as exc:
            await self._record_failure_event(
                context=context,
                tool_name=request.tool_name,
                scopes=scopes,
                error=exc,
                attempt_count=0,
                duration_ms=None,
            )
            raise

        attempts = retry_attempts_for_request(
            definition=entry.definition,
            default_max_retries=self._settings.defaults.max_retries,
            idempotency_key=request.idempotency_key,
        )

        for attempt_count in range(1, attempts + 1):
            started_at = perf_counter()
            await self._record_started_event(
                context=context,
                tool_name=entry.logical_name,
                scopes=scopes,
                stream=False,
                timeout_seconds=timeout_seconds,
                request=request,
                arguments=arguments,
                attempt_count=attempt_count,
            )
            adapter_request = self._build_adapter_request(
                entry=entry,
                arguments=arguments,
                request=request,
                timeout_seconds=timeout_seconds,
                scopes=scopes,
                context=context,
            )
            try:
                raw_result = await self._mcp_adapter.call_tool(request=adapter_request)
            except BaseException as exc:
                runtime_error = normalize_runtime_error(exc)
                if attempt_count < attempts and is_retryable_error(
                    runtime_error,
                    definition=entry.definition,
                    idempotency_key=request.idempotency_key,
                ):
                    continue

                await self._record_failure_event(
                    context=context,
                    tool_name=entry.logical_name,
                    scopes=scopes,
                    error=runtime_error,
                    attempt_count=attempt_count,
                    duration_ms=self._duration_ms(started_at),
                    status=(
                        "cancelled"
                        if isinstance(runtime_error, ToolCancelledError)
                        else "failed"
                    ),
                )
                raise runtime_error

            retry_error = result_retry_error(raw_result)
            if retry_error is not None and attempt_count < attempts and is_retryable_error(
                retry_error,
                definition=entry.definition,
                idempotency_key=request.idempotency_key,
            ):
                continue

            duration_ms = self._duration_ms(started_at)
            result = self._result_normalizer.normalize_result(
                entry.definition,
                raw_result,
                duration_ms=duration_ms,
            )
            if result.success:
                await self._record_completed_event(
                    context=context,
                    result=result,
                    scopes=scopes,
                    attempt_count=attempt_count,
                    duration_ms=duration_ms,
                )
            else:
                await self._record_failure_event(
                    context=context,
                    tool_name=entry.logical_name,
                    scopes=scopes,
                    error=retry_error,
                    attempt_count=attempt_count,
                    duration_ms=duration_ms,
                    status=result.status,
                    error_code=None if result.error_detail is None else result.error_detail.code,
                    retryable=(
                        None
                        if result.error_detail is None
                        else result.error_detail.retryable
                    ),
                )
            return result

        raise RuntimeError("Tool execution attempts exhausted without a result.")

    async def _prepare_execution(
        self,
        *,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
        action: PolicyAction,
        scopes: ToolScopes,
        require_streaming: bool,
    ) -> tuple[ToolRegistryEntry, dict[str, Any], int]:
        try:
            entry = self._registry.resolve_entry(request.tool_name)
        except ToolNotFoundError as exc:
            decision = await self._evaluate_policy(
                action=action,
                tool_name=request.tool_name,
                context=context,
                scopes=scopes,
                definition=None,
                require_streaming=require_streaming,
                idempotency_key_present=request.idempotency_key is not None,
            )
            if not decision.allowed:
                raise self._policy_denied_error(decision) from exc
            raise

        decision = await self._evaluate_policy(
            action=action,
            tool_name=entry.logical_name,
            context=context,
            scopes=scopes,
            definition=entry.definition,
            require_streaming=require_streaming,
            idempotency_key_present=request.idempotency_key is not None,
        )
        if not decision.allowed:
            raise self._policy_denied_error(decision)

        if require_streaming and not entry.definition.supports_streaming:
            raise ToolDisabledError(
                f"Tool '{entry.logical_name}' does not support streaming execution."
            )

        arguments = self._argument_validator.validate(entry.definition, request.arguments)
        timeout_seconds = self._effective_timeout(
            request=request,
            definition=entry.definition,
            stream=require_streaming,
        )
        return entry, arguments, timeout_seconds

    async def _evaluate_policy(
        self,
        *,
        action: PolicyAction,
        tool_name: str,
        context: OrchestrationContext,
        scopes: ToolScopes,
        definition: ResolvedToolDefinition | None,
        require_streaming: bool = False,
        idempotency_key_present: bool = False,
    ) -> PolicyDecision:
        request = build_tool_policy_request(
            action=action,
            component=self._component,
            tool_name=tool_name,
            scopes=scopes,
            context=context,
            tool_known=definition is not None,
            tool_enabled=False if definition is None else definition.enabled,
            safety_level=None if definition is None else definition.safety_level,
            approval_required=False if definition is None else definition.approval_required,
            supports_streaming=False if definition is None else definition.supports_streaming,
            allowed_usecases=() if definition is None else definition.allowed_usecases,
            allowed_agents=() if definition is None else definition.allowed_agents,
            allowed_strategies=() if definition is None else definition.allowed_strategies,
            idempotency_key_present=idempotency_key_present,
            stream_requested=require_streaming,
        )
        return await context.policy.evaluate(request, context)

    def _build_adapter_request(
        self,
        *,
        entry: ToolRegistryEntry,
        arguments: Mapping[str, Any],
        request: ToolExecutionRequest,
        timeout_seconds: int,
        scopes: ToolScopes,
        context: OrchestrationContext,
    ) -> MCPToolCallRequest:
        metadata = {
            "logical_tool_name": entry.logical_name,
            "tool_group": scopes.tool_group,
            **dict(request.metadata),
        }
        return AdapterRequestMetadata(
            trace_id=context.request.trace_id or "trace_tool",
            session_id=context.request.session_id,
            idempotency_key=request.idempotency_key,
            timeout_seconds=timeout_seconds,
            metadata=metadata,
        ).to_mcp_request(
            mcp_tool_name=entry.mcp_tool_name,
            arguments=arguments,
        )

    async def _record_started_event(
        self,
        *,
        context: OrchestrationContext,
        tool_name: str,
        scopes: ToolScopes,
        stream: bool,
        timeout_seconds: int,
        request: ToolExecutionRequest,
        arguments: Mapping[str, Any],
        attempt_count: int,
    ) -> None:
        payload = {
            **scopes.summary(),
            "stream": stream,
            "timeout_seconds": timeout_seconds,
            "argument_count": len(arguments),
            "idempotency_key_present": request.idempotency_key is not None,
            "attempt_count": attempt_count,
        }
        if self._settings.defaults.trace_arguments:
            payload["arguments"] = redact_tool_payload(arguments, max_chars=1024)

        await self._record_event(
            context=context,
            event_type=TOOL_CALL_STARTED,
            tool_name=tool_name,
            payload=payload,
            status="started",
        )

    async def _record_completed_event(
        self,
        *,
        context: OrchestrationContext,
        result: ToolExecutionResult,
        scopes: ToolScopes,
        attempt_count: int,
        duration_ms: int,
    ) -> None:
        summary = result.summary
        payload = {
            **scopes.summary(),
            "status": result.status,
            "duration_ms": duration_ms,
            "attempt_count": attempt_count,
            "result_count": None if summary is None else summary.result_count,
            "bytes_returned": None if summary is None else summary.bytes_returned,
            "truncated": False if summary is None else summary.truncated,
            "content_block_count": len(result.content),
        }
        if self._settings.defaults.trace_results:
            payload["structured_content"] = redact_tool_payload(
                result.structured_content,
                max_chars=2048,
            )

        await self._record_event(
            context=context,
            event_type=TOOL_CALL_COMPLETED,
            tool_name=result.tool_name,
            duration_ms=float(duration_ms),
            payload=_drop_none_values(payload),
        )

    async def _record_failure_event(
        self,
        *,
        context: OrchestrationContext,
        tool_name: str,
        scopes: ToolScopes,
        error: ToolGatewayError | None,
        attempt_count: int,
        duration_ms: int | None,
        status: str = "failed",
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        resolved_retryable = retryable
        if resolved_retryable is None and error is not None:
            resolved_retryable = isinstance(error, (ToolCancelledError,)) and False
        await self._record_event(
            context=context,
            event_type=TOOL_CALL_FAILED,
            tool_name=tool_name,
            duration_ms=None if duration_ms is None else float(duration_ms),
            payload=_drop_none_values(
                {
                    **scopes.summary(),
                    "status": status,
                    "attempt_count": attempt_count,
                    "retryable": resolved_retryable,
                }
            ),
            status=status,
            severity="warning",
            error_type=None if error is None else type(error).__name__,
            error_code=error_code or _error_code_for_error(error),
            retryable=resolved_retryable,
        )

    async def _record_event(
        self,
        *,
        context: OrchestrationContext,
        event_type: str,
        tool_name: str,
        payload: Mapping[str, Any],
        status: str = "completed",
        severity: str = "info",
        duration_ms: float | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        try:
            await context.trace.record_event(
                TraceEvent(
                    trace_id=context.request.trace_id or "trace_tool",
                    session_id=context.request.session_id,
                    event_type=event_type,
                    component=self._component,
                    timestamp=datetime.now(UTC),
                    status=status,
                    severity=severity,
                    user_id=context.request.user_id,
                    usecase=context.request.usecase,
                    agent_name=self._optional_text(
                        context.runtime_metadata.get("agent_name")
                    ),
                    strategy_name=self._optional_text(
                        context.runtime_metadata.get("strategy_name")
                    ),
                    tool_name=tool_name,
                    duration_ms=duration_ms,
                    error_type=error_type,
                    error_code=error_code,
                    retryable=retryable,
                    payload=dict(payload),
                )
            )
        except Exception:
            return None

    def _effective_timeout(
        self,
        *,
        request: ToolExecutionRequest,
        definition: ResolvedToolDefinition,
        stream: bool,
    ) -> int:
        if request.timeout_seconds is not None and request.timeout_seconds > 0:
            return request.timeout_seconds
        if stream:
            return max(definition.timeout_seconds, self._settings.defaults.stream_timeout_seconds)
        return definition.timeout_seconds

    def _effective_scopes(
        self,
        scopes: ToolScopes | Mapping[str, Any],
        context: OrchestrationContext,
    ) -> ToolScopes:
        resolved_scopes = scopes if isinstance(scopes, ToolScopes) else ToolScopes(**dict(scopes))
        return ToolScopes(
            user_id=resolved_scopes.user_id or context.request.user_id,
            project_id=resolved_scopes.project_id,
            tenant_id=resolved_scopes.tenant_id,
            session_id=resolved_scopes.session_id or context.request.session_id,
            agent_name=resolved_scopes.agent_name
            or self._optional_text(context.runtime_metadata.get("agent_name")),
            usecase=resolved_scopes.usecase or context.request.usecase,
            tool_group=resolved_scopes.tool_group,
            tags=resolved_scopes.tags,
            metadata=dict(resolved_scopes.metadata),
        )

    def _policy_scope(
        self,
        scopes: ToolScopes,
        context: OrchestrationContext,
    ) -> dict[str, Any]:
        return {
            "user_id": scopes.user_id or context.request.user_id,
            "project_id": scopes.project_id,
            "tenant_id": scopes.tenant_id,
            "session_id": scopes.session_id or context.request.session_id,
            "agent_name": scopes.agent_name
            or self._optional_text(context.runtime_metadata.get("agent_name")),
            "strategy_name": self._optional_text(
                context.runtime_metadata.get("strategy_name")
            ),
            "usecase": scopes.usecase or context.request.usecase,
            "usecase_name": scopes.usecase or context.request.usecase,
            "tool_group": scopes.tool_group,
            "tags": list(scopes.tags),
        }

    def _policy_denied_error(self, decision: PolicyDecision) -> ToolPolicyDeniedError:
        reason = decision.reason or "Tool execution was denied by policy."
        if decision.requires_approval:
            return ToolPolicyApprovalRequiredError(reason)
        return ToolPolicyDeniedError(reason)

    def _duration_ms(self, started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)

    def _optional_text(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None


def _to_public_definition(entry: ToolRegistryEntry) -> ToolDefinition:
    definition = entry.definition
    return ToolDefinition(
        name=definition.logical_name,
        description=definition.description,
        input_schema={} if definition.input_schema is None else dict(definition.input_schema),
        source=entry.source,
        output_schema=(
            None if definition.output_schema is None else dict(definition.output_schema)
        ),
        enabled=definition.enabled,
        execution_modes=definition.execution_modes,
        safety_level=definition.safety_level,
        approval_required=definition.approval_required,
        tags=definition.tags,
        metadata={},
    )


def _error_code_for_error(error: ToolGatewayError | None) -> str | None:
    if error is None:
        return None
    if isinstance(error, ToolPolicyDeniedError):
        return "tool_policy_denied"
    if isinstance(error, ToolNotFoundError):
        return "tool_not_found"
    if isinstance(error, ToolDisabledError):
        return "tool_disabled"
    if isinstance(error, ToolArgumentValidationError):
        return "tool_argument_validation_failed"
    if isinstance(error, ToolCancelledError):
        return "tool_cancelled"
    if isinstance(error, ToolGatewayError):
        return "tool_execution_failed"
    return None


def _drop_none_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
