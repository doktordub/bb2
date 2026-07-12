# MCP Visualization Phase 7 Threat Model Update

**Document:** `mcp-visualization-phase7-threat-model.md`  
**Phase:** 7  
**Scope:** Reporting MCP visualization tool hardening

## Summary

Phase 7 hardens `reporting.query_metric_series` by treating output strictly as bounded structured data, enforcing trusted scope, and limiting provider failure blast radius.

## Threats Addressed

1. Credential smuggling through tool arguments

- Shared MCP tool guards reject secret-like keys and bearer or JWT-like values.
- Reporting service now repeats that validation on normalized query input so direct service calls cannot bypass it.

2. Cross-scope data access

- Trusted scope remains provider-owned and is applied in the reporting service.
- Caller-supplied overrides for trusted scope keys are rejected with `unauthorized_scope`.

3. Cache poisoning or cache-key secret retention

- Cache keys now use a hashed fingerprint of approved normalized request fields.
- Secret-like requests are rejected before a cache key is built.

4. Actor-blind throttling

- Rate-limit keys now include the trusted caller identity plus a hashed trusted-scope fingerprint.
- Raw scope values do not appear in the limiter key.

5. Provider instability under retries or concurrency spikes

- Provider calls now run behind a bounded async semaphore.
- Retry attempts are bounded and limited to retryable failures.
- Repeated retryable failures open a local circuit and temporarily reject new provider calls until the reset window passes.

6. Misleading readiness when a loaded tool becomes unhealthy

- Required degraded tools now fail readiness.
- Optional degraded tools lower health without blocking readiness.

7. Prompt or tool-output injection

- Reporting output remains validated `structured_dataset_v1` data.
- The tool never returns runtime instructions, executable code, renderer code, or backend workflow objects.

## Residual Risk

- The current provider is fixture-backed and does not exercise a live outbound credential flow; future providers must add least-privilege outbound-auth integration tests.
- The circuit breaker is process-local. Multi-process deployments would need shared state only if provider protection must be synchronized globally.