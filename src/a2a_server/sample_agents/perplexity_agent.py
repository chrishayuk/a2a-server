# a2a_server/sample_agents/perplexity_agent.py
"""
Perplexity Agent (SSE) - FIXED version with proper exports and initialization
---------------------------------------------------------------------------

This fixes the import issues by providing proper module-level exports
while preventing double agent creation.
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


def create_perplexity_agent(**kwargs):
    """
    Create a perplexity agent with configurable parameters.
    
    Args:
        **kwargs: Configuration parameters passed from YAML
    """
    # Extract session-related parameters with defaults
    enable_sessions = kwargs.get('enable_sessions', True)  # Default to True for research continuity
    enable_tools = kwargs.get('enable_tools', True)        # Default to True for MCP tools
    debug_tools = kwargs.get('debug_tools', False)
    infinite_context = kwargs.get('infinite_context', True)
    token_threshold = kwargs.get('token_threshold', 6000)  # Higher for research
    max_turns_per_segment = kwargs.get('max_turns_per_segment', 30)
    session_ttl_hours = kwargs.get('session_ttl_hours', 24)
    
    # Extract other configurable parameters
    provider = kwargs.get('provider', 'openai')
    model = kwargs.get('model', 'gpt-4o')  # More capable model for research
    streaming = kwargs.get('streaming', True)
    
    # MCP configuration
    mcp_servers = kwargs.get('mcp_servers', ["perplexity_server"])
    tool_namespace = kwargs.get('tool_namespace', "sse")
    
    log.info(f"🔍 Creating perplexity agent with sessions: {enable_sessions}")
    log.info(f"🔍 Using model: {provider}/{model}")
    log.info(f"🔍 MCP SSE tools enabled: {enable_tools}")
    
    try:
        # Ensure the config directory exists
        CFG_FILE.parent.mkdir(exist_ok=True)
        
        agent = SSEChukAgent(
            name="perplexity_agent",
            provider=provider,
            model=model,
            description="Perplexity-style research agent with MCP SSE tools",
            instruction="""You are a helpful research assistant with access to real-time search capabilities.

🔍 CAPABILITIES:
- Real-time web search and information retrieval
- Access to current news, data, and developments
- Fact-checking and source verification
- Research synthesis and analysis

📋 RESEARCH APPROACH:
1. Use your search tools to find current, relevant information
2. Cross-reference multiple sources when possible
3. Provide citations and source links
4. Synthesize information into clear, comprehensive responses
5. Acknowledge limitations and suggest follow-up research when appropriate

🎯 RESPONSE STYLE:
- Start with a direct answer to the question
- Provide supporting details with proper citations
- Use clear structure (headers, bullet points, etc.)
- Include relevant links and sources
- Be precise about the recency and reliability of information

When MCP tools are available, use them to provide accurate, up-to-date information. 
If tools are not available, provide helpful responses based on your training data and clearly indicate the limitations.""",
            streaming=streaming,
            
            # Session management
            enable_sessions=enable_sessions,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            session_ttl_hours=session_ttl_hours,
            
            # MCP SSE tools
            enable_tools=enable_tools,
            debug_tools=debug_tools,
            mcp_servers=mcp_servers,
            tool_namespace=tool_namespace,
            
            # Pass through any other kwargs
            **{k: v for k, v in kwargs.items() if k not in [
                'enable_sessions', 'enable_tools', 'debug_tools',
                'infinite_context', 'token_threshold', 'max_turns_per_segment',
                'session_ttl_hours', 'provider', 'model', 'streaming',
                'mcp_servers', 'tool_namespace'
            ]}
        )
        
        log.info(f"✅ Successfully created perplexity_agent: {type(agent)}")
        
        # Debug logging
        log.info(f"🔍 PERPLEXITY AGENT CREATED: {type(agent)}")
        log.info(f"🔍 Internal sessions enabled: {agent.enable_sessions}")
        log.info(f"🔍 Tools enabled: {agent.enable_tools}")
        
        if enable_sessions:
            log.info(f"🔍 Agent will manage research sessions internally")
        else:
            log.info(f"🔍 External sessions will be managed by handler")
        
        return agent
        
    except Exception as e:
        log.error(f"Failed to create perplexity_agent: {e}")
        log.exception("Full creation error:")
        
        # Create a minimal fallback ChukAgent
        fallback_agent = ChukAgent(
            name="perplexity_agent",
            provider=provider,
            model=model,
            description="Research assistant (SSE tools unavailable)",
            instruction="I'm a research assistant, but my real-time search tools are currently unavailable. I can still help with analysis and provide information from my training data.",
            streaming=streaming,
            enable_sessions=enable_sessions,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            session_ttl_hours=session_ttl_hours
        )
        
        log.warning("Created fallback perplexity agent without SSE tools")
        return fallback_agent


# 🔧 FIXED: Provide proper module-level exports for backward compatibility
# This solves the import error while preventing double creation
perplexity_agent = None  # Initialize to None

def get_perplexity_agent():
    """Get or create a default perplexity agent instance."""
    global perplexity_agent
    if perplexity_agent is None:
        perplexity_agent = create_perplexity_agent()
    return perplexity_agent

# Export the factory function as the main interface
__all__ = ['create_perplexity_agent', 'get_perplexity_agent', 'SSEChukAgent']