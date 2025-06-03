"""
Perplexity Agent (SSE) - Clean version with proper MCP authentication
----------------------------------------------------------------------

Environment Variables:
~~~~~~~~~~~~~~~~~~~~~
• **MCP_BEARER_TOKEN** - Bearer token for MCP server authentication
  Example: ``export MCP_BEARER_TOKEN="Bearer your-token-here"``

• **MCP_SERVER_NAME_MAP** - JSON dict mapping *default* names → *override* names  
  Example: ``export MCP_SERVER_NAME_MAP='{"perplexity_server":"ppx_prod"}'``

• **MCP_SERVER_URL_MAP**  - JSON dict mapping *default* names → *override* URLs  
  Example: ``export MCP_SERVER_URL_MAP='{"perplexity_server":"https://ppx.internal:8020"}'``

The MCP_BEARER_TOKEN is automatically detected and used for authentication.
The name and URL maps are optional; if unset, values from perplexity_agent.mcp.json are used.
"""

import json
import logging
import os
import pathlib
from typing import Dict

from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
from chuk_tool_processor.mcp.setup_mcp_sse import setup_mcp_sse

log = logging.getLogger(__name__)
HERE = pathlib.Path(__file__).parent
CFG_FILE = HERE / "perplexity_agent.mcp.json"


# ---------------------------------------------------------------------------#
# Helper: load "name → value" override map from env or return an empty dict  #
# ---------------------------------------------------------------------------#
def _load_override(var: str) -> Dict[str, str]:
    """Load environment variable as JSON dict or return empty dict."""
    raw = os.getenv(var)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception as exc:
        log.warning("Ignoring invalid %s (%s)", var, exc)
        return {}


# ---------------------------------------------------------------------------#
# Clean SSE ChukAgent - No monkey patching required!                        #
# ---------------------------------------------------------------------------#
class SSEChukAgent(ChukAgent):
    """
    ChukAgent that connects to MCP servers via SSE transport.
    
    Automatically handles:
    - Bearer token authentication from MCP_BEARER_TOKEN environment variable
    - URL redirect fixes (trailing slash issue)
    - MCP protocol handshake and initialization
    - Tool discovery and registration
    """

    async def _initialize_tools(self) -> None:
        """Initialize MCP tools via SSE transport."""
        if self._tools_initialized or not self.enable_tools:
            return

        try:
            log.info("🚀 Initializing SSE ChukAgent")

            # 1) Read MCP server configuration
            with CFG_FILE.open() as fh:
                data = json.load(fh)

            # 2) Apply environment variable overrides
            name_override = _load_override("MCP_SERVER_NAME_MAP")
            url_override = _load_override("MCP_SERVER_URL_MAP")

            servers = [
                {
                    "name": name_override.get(default_name, default_name),
                    "url": url_override.get(default_name, cfg["url"]),
                    "transport": cfg.get("transport", "sse"),
                }
                for default_name, cfg in data.get("mcpServers", {}).items()
            ]

            if not servers:
                raise RuntimeError("No MCP servers defined in configuration")

            log.info("📡 Connecting to %d MCP server(s)", len(servers))
            for server in servers:
                log.info("  🔗 %s: %s", server["name"], server["url"])

            server_names = {i: srv["name"] for i, srv in enumerate(servers)}

            # 3) Initialize MCP connection with automatic bearer token detection
            namespace = self.tool_namespace or "sse"
            _, self.stream_manager = await setup_mcp_sse(
                servers=servers,
                server_names=server_names,
                namespace=namespace,
            )

            # Log successful connection
            for server in servers:
                log.info("✅ Connected to %s via SSE", server["url"])

            # 4) Complete tool registration via parent class
            await super()._initialize_tools()

            log.info("🎉 SSE ChukAgent initialization complete")

        except Exception:
            log.exception("❌ Failed to initialize SSE MCP connection")
            self.enable_tools = False  # Graceful degradation


# ---------------------------------------------------------------------------#
# Export the agent instance for YAML configuration                          #
# ---------------------------------------------------------------------------#
perplexity_agent = SSEChukAgent(
    name="perplexity_agent",
    description="Perplexity-style agent with MCP SSE tools",
    mcp_servers=["perplexity_server"],
    tool_namespace="sse", 
    streaming=True,
)