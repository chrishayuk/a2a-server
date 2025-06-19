"""
Perplexity Agent (SSE) - FIXED version with proper initialization
----------------------------------------------------------------

This fixes the main issues:
1. Tools initialization was happening in wrong method
2. SSE connection wasn't being established before schema generation
3. Missing error handling for when MCP servers are unavailable
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


class SSEChukAgent(ChukAgent):
    """
    ChukAgent that connects to MCP servers via SSE transport.
    
    FIXED: Properly handles initialization and graceful degradation.
    """

    def __init__(self, **kwargs):
        """Initialize with enable_tools defaulting to True for SSE agents."""
        # Ensure tools are enabled by default for SSE agents
        kwargs.setdefault('enable_tools', True)
        super().__init__(**kwargs)
        
        # Override tool namespace if not provided
        if not self.tool_namespace:
            self.tool_namespace = "sse"

    async def initialize_tools(self) -> None:
        """Initialize MCP tools via SSE transport - FIXED VERSION."""
        if self._tools_initialized:
            return

        try:
            log.info("🚀 Initializing SSE ChukAgent")

            # 1) Check if MCP config file exists
            if not CFG_FILE.exists():
                log.warning(f"MCP config file not found: {CFG_FILE}")
                log.info("Creating minimal config for testing...")
                
                # Create a minimal config for development/testing
                minimal_config = {
                    "mcpServers": {
                        "perplexity_server": {
                            "url": "http://localhost:8000/sse",
                            "transport": "sse"
                        }
                    }
                }
                
                CFG_FILE.parent.mkdir(exist_ok=True)
                with CFG_FILE.open('w') as f:
                    json.dump(minimal_config, f, indent=2)
                
                log.info(f"Created config file: {CFG_FILE}")

            # 2) Read MCP server configuration
            with CFG_FILE.open() as fh:
                data = json.load(fh)

            # 3) Apply environment variable overrides
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
                log.warning("No MCP servers defined in configuration")
                self._tools_initialized = True  # Mark as initialized but without tools
                return

            log.info("📡 Attempting to connect to %d MCP server(s)", len(servers))
            for server in servers:
                log.info("  🔗 %s: %s", server["name"], server["url"])

            server_names = {i: srv["name"] for i, srv in enumerate(servers)}

            # 4) Initialize MCP connection with automatic bearer token detection
            namespace = self.tool_namespace or "sse"
            
            try:
                _, self.stream_manager = await setup_mcp_sse(
                    servers=servers,
                    server_names=server_names,
                    namespace=namespace,
                )

                # Log successful connection
                for server in servers:
                    log.info("✅ Connected to %s via SSE", server["url"])

                # 5) Complete tool registration via parent class
                await super().initialize_tools()

                log.info("🎉 SSE ChukAgent initialization complete")
                self._tools_initialized = True

            except Exception as connection_error:
                log.warning(f"Failed to connect to MCP servers: {connection_error}")
                log.info("Operating without MCP tools (graceful degradation)")
                self._tools_initialized = True  # Mark as initialized but without tools
                self.stream_manager = None
                # Don't raise - allow agent to work without tools

        except Exception as e:
            log.error(f"❌ Failed to initialize SSE MCP connection: {e}")
            log.exception("Full initialization error:")
            self._tools_initialized = True  # Mark as initialized to prevent retry loops
            self.stream_manager = None
            # Graceful degradation - agent works without tools

    async def generate_tools_schema(self):
        """Generate tools schema with proper error handling."""
        if not self.stream_manager:
            log.info("No stream manager available - agent will work without tools")
            return []
        
        return await super().generate_tools_schema()

    async def get_available_tools(self):
        """Get available tools with proper error handling."""
        if not self.stream_manager:
            return []
        
        return await super().get_available_tools()


# Create the perplexity agent instance
try:
    # Ensure the config directory exists
    CFG_FILE.parent.mkdir(exist_ok=True)
    
    perplexity_agent = SSEChukAgent(
        name="perplexity_agent",
        description="Perplexity-style agent with MCP SSE tools",
        instruction="You are a helpful research assistant. When MCP tools are available, use them to provide accurate, up-to-date information. If tools are not available, provide helpful responses based on your training data.",
        mcp_servers=["perplexity_server"],
        tool_namespace="sse", 
        streaming=True,
        enable_tools=True,  # Explicitly enable tools
    )
    
    log.info(f"Successfully created perplexity_agent: {type(perplexity_agent)}")
    
except Exception as e:
    log.error(f"Failed to create perplexity_agent: {e}")
    log.exception("Full creation error:")
    
    # Create a minimal fallback
    class FallbackAgent:
        def __init__(self):
            self.name = "perplexity_agent_fallback"
            
        async def initialize_tools(self):
            pass
            
        async def generate_tools_schema(self):
            return []
    
    perplexity_agent = FallbackAgent()