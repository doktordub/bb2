from __future__ import annotations

from app.context import ToolRuntimeContext


def create_plugin(context: ToolRuntimeContext):
    del context
    raise RuntimeError("plugin startup failed")