"""Backend-owned tool argument validation using a bounded JSON Schema subset."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.tools.errors import ToolArgumentValidationError
from app.tools.models import ResolvedToolDefinition
from app.tools.redaction import find_secret_like_paths, format_paths

_DENYLIST_METADATA_KEYS = (
    "denylisted_fields",
    "denylisted_argument_fields",
    "argument_denylist",
)


class ToolArgumentValidator:
    """Validate tool arguments before any adapter call occurs."""

    def __init__(self, *, default_max_argument_bytes: int = 65536) -> None:
        self._default_max_argument_bytes = default_max_argument_bytes

    def validate(
        self,
        definition: ResolvedToolDefinition,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return a normalized JSON-safe argument object or raise validation errors."""

        normalized = _to_plain_json_value(arguments)
        if not isinstance(normalized, dict):
            raise ToolArgumentValidationError("Tool arguments must serialize to a JSON object.")

        payload_bytes = _json_size_bytes(normalized)
        max_argument_bytes = definition.max_argument_bytes or self._default_max_argument_bytes
        if payload_bytes > max_argument_bytes:
            raise ToolArgumentValidationError(
                f"Tool arguments exceed the configured size limit of {max_argument_bytes} bytes."
            )

        denylisted_paths = _find_denylisted_paths(
            normalized,
            denylisted_fields=_normalize_denylisted_fields(definition.metadata),
            path=("arguments",),
        )
        if denylisted_paths:
            rendered = format_paths(denylisted_paths)
            raise ToolArgumentValidationError(
                f"Tool arguments contain denylisted fields and were rejected: {rendered}."
            )

        secret_paths = find_secret_like_paths(normalized, path=("arguments",))
        if secret_paths:
            rendered = format_paths(secret_paths)
            raise ToolArgumentValidationError(
                f"Tool arguments contain secret-like fields and were rejected: {rendered}."
            )

        if definition.input_schema is not None:
            validate_json_value_against_schema(
                normalized,
                definition.input_schema,
                root_name="arguments",
            )

        return normalized


def validate_json_value_against_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    root_name: str,
) -> None:
    """Validate one JSON value against the supported schema subset."""

    _validate_against_schema(value, schema, path=(root_name,))


def _validate_against_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: tuple[str, ...],
) -> None:
    supported_types = _normalize_schema_types(schema.get("type"))
    if supported_types and not any(_matches_json_type(value, item) for item in supported_types):
        expected = ", ".join(supported_types)
        raise ToolArgumentValidationError(f"{_format_path(path)} must be of type: {expected}.")

    enum_values = schema.get("enum")
    if isinstance(enum_values, Sequence) and not isinstance(enum_values, str | bytes | bytearray):
        if value not in tuple(enum_values):
            allowed = ", ".join(repr(item) for item in enum_values)
            raise ToolArgumentValidationError(
                f"{_format_path(path)} must match one of: {allowed}."
            )

    if "const" in schema and value != schema["const"]:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must equal {schema['const']!r}."
        )

    if isinstance(value, dict):
        _validate_object(value, schema, path=path)
    elif isinstance(value, list):
        _validate_array(value, schema, path=path)
    elif isinstance(value, str):
        _validate_string(value, schema, path=path)
    elif _is_json_number(value):
        _validate_number(value, schema, path=path)


def _validate_object(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    path: tuple[str, ...],
) -> None:
    required = schema.get("required")
    if isinstance(required, Sequence) and not isinstance(required, str | bytes | bytearray):
        for field_name in required:
            if isinstance(field_name, str) and field_name not in value:
                raise ToolArgumentValidationError(
                    f"{_format_path(path + (field_name,))} is required."
                )

    min_properties = _coerce_int(schema.get("minProperties"))
    if min_properties is not None and len(value) < min_properties:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must contain at least {min_properties} properties."
        )

    max_properties = _coerce_int(schema.get("maxProperties"))
    if max_properties is not None and len(value) > max_properties:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must contain at most {max_properties} properties."
        )

    properties = schema.get("properties")
    property_schemas = properties if isinstance(properties, Mapping) else {}
    additional_properties = schema.get("additionalProperties", True)
    for key, item in value.items():
        child_path = path + (key,)
        child_schema = property_schemas.get(key)
        if isinstance(child_schema, Mapping):
            _validate_against_schema(item, child_schema, path=child_path)
            continue
        if additional_properties is False:
            raise ToolArgumentValidationError(f"{_format_path(child_path)} is not allowed.")
        if isinstance(additional_properties, Mapping):
            _validate_against_schema(item, additional_properties, path=child_path)


def _validate_array(
    value: Sequence[Any],
    schema: Mapping[str, Any],
    *,
    path: tuple[str, ...],
) -> None:
    min_items = _coerce_int(schema.get("minItems"))
    if min_items is not None and len(value) < min_items:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must contain at least {min_items} items."
        )

    max_items = _coerce_int(schema.get("maxItems"))
    if max_items is not None and len(value) > max_items:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must contain at most {max_items} items."
        )

    items_schema = schema.get("items")
    if isinstance(items_schema, Mapping):
        for index, item in enumerate(value):
            _validate_against_schema(item, items_schema, path=path + (str(index),))


def _validate_string(value: str, schema: Mapping[str, Any], *, path: tuple[str, ...]) -> None:
    min_length = _coerce_int(schema.get("minLength"))
    if min_length is not None and len(value) < min_length:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must be at least {min_length} characters long."
        )

    max_length = _coerce_int(schema.get("maxLength"))
    if max_length is not None and len(value) > max_length:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must be at most {max_length} characters long."
        )


def _validate_number(value: int | float, schema: Mapping[str, Any], *, path: tuple[str, ...]) -> None:
    minimum = _coerce_number(schema.get("minimum"))
    if minimum is not None and value < minimum:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must be greater than or equal to {minimum}."
        )

    maximum = _coerce_number(schema.get("maximum"))
    if maximum is not None and value > maximum:
        raise ToolArgumentValidationError(
            f"{_format_path(path)} must be less than or equal to {maximum}."
        )


def _normalize_schema_types(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        collected: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized and normalized not in collected:
                    collected.append(normalized)
        return tuple(collected)
    return ()


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return _is_json_number(value)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _is_json_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _normalize_denylisted_fields(metadata: Mapping[str, Any]) -> frozenset[str]:
    collected: list[str] = []
    for key in _DENYLIST_METADATA_KEYS:
        raw_value = metadata.get(key)
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized and normalized not in collected:
                collected.append(normalized)
            continue
        if isinstance(raw_value, Sequence) and not isinstance(raw_value, str | bytes | bytearray):
            for item in raw_value:
                if not isinstance(item, str):
                    continue
                normalized = item.strip().lower()
                if normalized and normalized not in collected:
                    collected.append(normalized)
    return frozenset(collected)


def _find_denylisted_paths(
    value: object,
    *,
    denylisted_fields: frozenset[str],
    path: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    if not denylisted_fields:
        return ()

    matches: list[tuple[str, ...]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            next_path = path + (key_text,)
            path_text = ".".join(part.lower() for part in next_path[1:])
            normalized_key = key_text.strip().lower()
            if normalized_key in denylisted_fields or path_text in denylisted_fields:
                matches.append(next_path)
            matches.extend(
                _find_denylisted_paths(
                    item,
                    denylisted_fields=denylisted_fields,
                    path=next_path,
                )
            )
        return tuple(matches)

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            matches.extend(
                _find_denylisted_paths(
                    item,
                    denylisted_fields=denylisted_fields,
                    path=path + (str(index),),
                )
            )
    return tuple(matches)


def _to_plain_json_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_plain_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_to_plain_json_value(item) for item in value]
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise ToolArgumentValidationError(
        f"Tool arguments must be JSON-serializable. Unsupported value type: {type(value).__name__}."
    )


def _json_size_bytes(value: object) -> int:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ToolArgumentValidationError("Tool arguments must be JSON-serializable.") from exc
    return len(payload.encode("utf-8"))


def _coerce_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _coerce_number(value: object) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    return None


def _format_path(path: Sequence[str]) -> str:
    return format_paths((tuple(path),)) or "value"
