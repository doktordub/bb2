"""Persistence-local SQL builders for SQLite trace read and search queries."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.trace import TraceSearchFilters


@dataclass(frozen=True, slots=True)
class SqliteTraceQuery:
    """Parameterized SQLite statement plus bound parameters."""

    sql: str
    parameters: tuple[object, ...]


def normalize_trace_read_limit(limit: int | None, *, max_limit: int) -> int:
    """Clamp trace-read limits to a safe adapter-local range."""

    if max_limit < 1:
        raise ValueError("Trace read max_limit must be at least 1.")
    if limit is None:
        return max_limit
    if limit < 0:
        raise ValueError("Trace read limit must be greater than or equal to 0.")
    if limit == 0:
        return 0
    return min(limit, max_limit)


def normalize_trace_search_limit(limit: int, *, max_limit: int) -> int:
    """Clamp trace-search limits to the configured maximum."""

    if max_limit < 1:
        raise ValueError("Trace search max_limit must be at least 1.")
    if limit < 1:
        raise ValueError("Trace search limit must be at least 1.")
    return min(limit, max_limit)


def build_read_trace_summary_query(*, trace_id: str) -> SqliteTraceQuery:
    """Return the parameterized summary lookup for one trace."""

    return SqliteTraceQuery(
        sql="""
        SELECT
            trace_id,
            parent_trace_id,
            session_id_hash,
            user_id_hash,
            usecase,
            operation,
            route_template,
            status,
            severity,
            started_at,
            ended_at,
            last_event_at,
            duration_ms,
            event_count,
            error_count,
            agent_name,
            strategy_name,
            llm_profile,
            provider,
            model,
            tool_name,
            error_type,
            error_code,
            metadata_json
        FROM trace_runs
        WHERE trace_id = ?
        """.strip(),
        parameters=(trace_id,),
    )


def build_read_trace_events_query(*, trace_id: str, limit: int) -> SqliteTraceQuery:
    """Return the parameterized ordered-event lookup for one trace."""

    return SqliteTraceQuery(
        sql="""
        SELECT
            event_id,
            trace_id,
            sequence_no,
            parent_event_id,
            event_name,
            event_type,
            status,
            severity,
            component,
            timestamp,
            duration_ms,
            session_id,
            session_id_hash,
            user_id,
            user_id_hash,
            usecase,
            agent_name,
            strategy_name,
            llm_profile,
            provider,
            model,
            tool_name,
            error_type,
            error_code,
            retryable,
            payload_json,
            payload_size_bytes,
            redaction_version
        FROM trace_events
        WHERE trace_id = ?
        ORDER BY sequence_no ASC
        LIMIT ?
        """.strip(),
        parameters=(trace_id, limit),
    )


def build_search_trace_summaries_query(
    *,
    filters: TraceSearchFilters,
    max_limit: int,
) -> SqliteTraceQuery:
    """Return a bounded, parameterized summary search query."""

    conditions: list[str] = []
    parameters: list[object] = []

    if filters.started_after is not None:
        conditions.append("r.started_at >= ?")
        parameters.append(filters.started_after.isoformat())

    if filters.started_before is not None:
        conditions.append("r.started_at < ?")
        parameters.append(filters.started_before.isoformat())

    if filters.status is not None:
        conditions.append("r.status = ?")
        parameters.append(filters.status)

    if filters.severity is not None:
        conditions.append("r.severity = ?")
        parameters.append(filters.severity)

    if filters.usecase is not None:
        conditions.append("r.usecase = ?")
        parameters.append(filters.usecase)

    if filters.session_id_hash is not None:
        conditions.append("r.session_id_hash = ?")
        parameters.append(filters.session_id_hash)

    if filters.user_id_hash is not None:
        conditions.append("r.user_id_hash = ?")
        parameters.append(filters.user_id_hash)

    if filters.agent_name is not None:
        conditions.append("r.agent_name = ?")
        parameters.append(filters.agent_name)

    if filters.strategy_name is not None:
        conditions.append("r.strategy_name = ?")
        parameters.append(filters.strategy_name)

    if filters.llm_profile is not None:
        conditions.append("r.llm_profile = ?")
        parameters.append(filters.llm_profile)

    if filters.tool_name is not None:
        conditions.append("r.tool_name = ?")
        parameters.append(filters.tool_name)

    if filters.error_type is not None:
        conditions.append("r.error_type = ?")
        parameters.append(filters.error_type)

    if filters.errors_only:
        conditions.append("r.error_count > 0")

    if filters.event_name is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM trace_events e WHERE e.trace_id = r.trace_id AND e.event_name = ?)"
        )
        parameters.append(filters.event_name)

    if filters.event_type is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM trace_events e WHERE e.trace_id = r.trace_id AND e.event_type = ?)"
        )
        parameters.append(filters.event_type)

    where_sql = ""
    if conditions:
        where_sql = "\nWHERE " + "\n  AND ".join(conditions)

    limit = normalize_trace_search_limit(filters.limit, max_limit=max_limit)
    parameters.append(limit)

    return SqliteTraceQuery(
        sql=(
            """
            SELECT
                r.trace_id,
                r.parent_trace_id,
                r.session_id_hash,
                r.user_id_hash,
                r.usecase,
                r.operation,
                r.route_template,
                r.status,
                r.severity,
                r.started_at,
                r.ended_at,
                r.last_event_at,
                r.duration_ms,
                r.event_count,
                r.error_count,
                r.agent_name,
                r.strategy_name,
                r.llm_profile,
                r.provider,
                r.model,
                r.tool_name,
                r.error_type,
                r.error_code,
                r.metadata_json
            FROM trace_runs r
            """.strip()
            + where_sql
            + "\nORDER BY r.started_at DESC, r.trace_id DESC\nLIMIT ?"
        ),
        parameters=tuple(parameters),
    )