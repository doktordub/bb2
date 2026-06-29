"""Internal MCP client adapter surface for the backend tooling runtime package."""

from app.tools.mcp.auth import (
    MCPAuthProvider,
    NoOpMCPAuthProvider,
    OAuthClientCredentialsMCPAuthProvider,
    StaticTokenMCPAuthProvider,
    build_mcp_auth_provider,
)
from app.tools.mcp.client_adapter import DefaultMCPClientAdapter
from app.tools.mcp.fake import FakeMCPClientAdapter
from app.tools.mcp.protocol_models import (
    MCPClientAdapter,
    MCPHealthResult,
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolContent,
    MCPToolDefinition,
    MCPToolStreamEvent,
)
from app.tools.mcp.transport import DefaultMCPTransport, MCPTransport

__all__ = [
    "build_mcp_auth_provider",
    "DefaultMCPClientAdapter",
    "DefaultMCPTransport",
    "FakeMCPClientAdapter",
    "MCPAuthProvider",
    "MCPClientAdapter",
    "MCPHealthResult",
    "MCPTransport",
    "MCPToolCallRequest",
    "MCPToolCallResult",
    "MCPToolContent",
    "MCPToolDefinition",
    "MCPToolStreamEvent",
    "NoOpMCPAuthProvider",
    "OAuthClientCredentialsMCPAuthProvider",
    "StaticTokenMCPAuthProvider",
]