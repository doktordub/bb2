"""Secret resolution abstractions for MCP plugins and common services."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr

from app.errors import MCPSecretError
from app.schemas import SecretsSettings


ENV_NAME_PATTERN = re.compile(r"[^A-Za-z0-9]+")


class SecretResolver(Protocol):
    """Minimal interface for secret resolution."""

    @property
    def provider_name(self) -> str:
        ...

    def get(
        self,
        name: str,
        *,
        env_var: str | None = None,
        required: bool = True,
    ) -> SecretStr | None:
        ...


@dataclass(frozen=True, slots=True)
class EnvironmentSecretResolver:
    """Environment-backed secret resolver with prefix allow-list enforcement."""

    settings: SecretsSettings
    environ: Mapping[str, str]
    provider_name: str = "env"

    def get(
        self,
        name: str,
        *,
        env_var: str | None = None,
        required: bool = True,
    ) -> SecretStr | None:
        return self._resolve(
            name=name,
            env_var=env_var,
            required=required,
            enforce_tool_prefix_policy=False,
        )

    def for_tools(self) -> SecretResolver:
        return ToolSecretResolver(parent=self)

    def _resolve(
        self,
        *,
        name: str,
        env_var: str | None,
        required: bool,
        enforce_tool_prefix_policy: bool,
    ) -> SecretStr | None:
        target_env_var = env_var or self._default_env_var(name)
        if enforce_tool_prefix_policy and not self._is_allowed_env_var(target_env_var, name):
            raise MCPSecretError(
                f"Environment variable {target_env_var!r} is not allowed by MCP secret policy."
            )

        value = self.environ.get(target_env_var)
        if value not in (None, ""):
            return SecretStr(value)
        if required:
            raise MCPSecretError(
                f"Required secret {name!r} was not found in environment variable "
                f"{target_env_var!r}."
            )
        return None

    def _default_env_var(self, name: str) -> str:
        normalized = ENV_NAME_PATTERN.sub("_", name).strip("_").upper()
        if not normalized:
            raise MCPSecretError("Secret names must resolve to a valid environment variable.")
        return normalized

    def _is_allowed_env_var(self, env_var: str, name: str) -> bool:
        if env_var == self._default_env_var(name):
            return True
        return any(env_var.startswith(prefix) for prefix in self.settings.allow_tool_env_prefixes)


@dataclass(frozen=True, slots=True)
class ToolSecretResolver:
    """Tool-scoped secret resolver that enforces configured environment prefixes."""

    parent: EnvironmentSecretResolver

    @property
    def provider_name(self) -> str:
        return self.parent.provider_name

    def get(
        self,
        name: str,
        *,
        env_var: str | None = None,
        required: bool = True,
    ) -> SecretStr | None:
        return self.parent._resolve(
            name=name,
            env_var=env_var,
            required=required,
            enforce_tool_prefix_policy=True,
        )