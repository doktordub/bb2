"""Concrete policy runtime used by gateway and orchestration code."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
	"DefaultPolicyService": ("app.policy.service", "DefaultPolicyService"),
	"PolicyProfileSettings": ("app.policy.models", "PolicyProfileSettings"),
	"PolicySettings": ("app.policy.models", "PolicySettings"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
	if name not in _EXPORTS:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

	module_name, attribute_name = _EXPORTS[name]
	module = import_module(module_name)
	return getattr(module, attribute_name)