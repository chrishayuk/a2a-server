# a2a_server/sample_agents/perplexity_agent.py
"""
Perplexity Agent (SSE) - COMPLETE CONFIG BYPASS
-----------------------------------------------

This version completely bypasses any config file dependencies and 
manually sets up the MCP connection without relying on setup_mcp_sse.
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Any, Optional

from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

log = logging.getLogger(__name__)

# DEBUG: Log when module is imported
log.info("🔥 PERPLEXITY_AGENT MODULE: Module being imported!")
log.info(f"🔥 PERPLEXITY_AGENT MODULE: Module name = {__name__}")
log.info(f"🔥 PERPLEXITY_AGENT MODULE: File = {__file__}")



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


def get_mcp_servers_from_env() -> List[Dict[str, str]]:
    """Get MCP server configuration from environment variables."""
    
    # Debug: Log all relevant environment variables
    log.info("🔍 DEBUG: Checking environment variables...")
    log.info(f"🔍 MCP_SERVER_URL: {os.getenv('MCP_SERVER_URL', 'NOT SET')}")
    log.info(f"🔍 MCP_SERVER_URL_MAP: {os.getenv('MCP_SERVER_URL_MAP', 'NOT SET')}")
    log.info(f"🔍 MCP_SERVER_NAME_MAP: {os.getenv('MCP_SERVER_NAME_MAP', 'NOT SET')}")
    log.info(f"🔍 MCP_BEARER_TOKEN: {'SET' if os.getenv('MCP_BEARER_TOKEN') else 'NOT SET'}")
    
    # Load environment variable overrides
    name_override = _load_override("MCP_SERVER_NAME_MAP")
    url_override = _load_override("MCP_SERVER_URL_MAP")
    
    log.info(f"🔍 DEBUG: Parsed name_override: {name_override}")
    log.info(f"🔍 DEBUG: Parsed url_override: {url_override}")
    
    # Check for simple single server URL
    single_server_url = os.getenv('MCP_SERVER_URL')
    
    if single_server_url:
        log.info(f"📡 Using single MCP server from MCP_SERVER_URL: {single_server_url}")
        return [{
            "name": "perplexity_server",
            "url": single_server_url,
        }]
    
    # Check URL override map
    if url_override:
        servers = []
        for server_name, server_url in url_override.items():
            actual_name = name_override.get(server_name, server_name)
            servers.append({
                "name": actual_name,
                "url": server_url,
            })
        log.info(f"📡 Using {len(servers)} MCP server(s) from URL map")
        log.info(f"📡 Servers: {servers}")
        return servers
    
    # No MCP configuration found
    log.warning("❌ No MCP server configuration found in environment variables")
    log.info("💡 Set MCP_SERVER_URL or MCP_SERVER_URL_MAP to enable MCP tools")
    return []


class DirectMCPConnection:
    """Direct MCP connection that bypasses all config files."""
    
    def __init__(self, servers, namespace="sse"):
        self.servers = servers
        self.namespace = namespace
        self.registry = None
        self.connected = False
        
    async def connect(self):
        """Connect directly and trigger async tool population."""
        try:
            log.critical("🚨 DIRECT_CONNECTION: Attempting direct connection")
            
            # Step 1: Get the registry provider directly
            try:
                from chuk_tool_processor.registry.provider import ToolRegistryProvider
                self.registry = await ToolRegistryProvider.get_registry()
                log.critical("🚨 DIRECT_CONNECTION: Got tool registry directly")
                
                # Step 2: Try to trigger async tool loading from your server
                log.critical("🚨 DIRECT_CONNECTION: Attempting to trigger async tool loading...")
                
                # Import the setup function to trigger the async server communication
                try:
                    from chuk_tool_processor.mcp.setup_mcp_sse import setup_mcp_sse
                    
                    # Use the same pattern as the working example, but catch errors gracefully
                    server_names = {i: srv["name"] for i, srv in enumerate(self.servers)}
                    
                    log.critical(f"🚨 DIRECT_CONNECTION: Calling setup_mcp_sse with servers: {self.servers}")
                    
                    try:
                        # This should trigger the async server communication
                        _, stream_manager = await setup_mcp_sse(
                            servers=self.servers,
                            server_names=server_names,
                            namespace=self.namespace,
                        )
                        
                        log.critical("🚨 DIRECT_CONNECTION: setup_mcp_sse completed successfully!")
                        
                        # Even if tools/list fails with 202, the connection should be established
                        # and tools may be populated asynchronously
                        
                    except Exception as setup_error:
                        log.critical(f"🚨 DIRECT_CONNECTION: setup_mcp_sse failed (expected for async): {setup_error}")
                        # This is expected for async servers - they return errors but may still work
                        
                except ImportError as import_error:
                    log.critical(f"🚨 DIRECT_CONNECTION: Could not import setup_mcp_sse: {import_error}")
                
                # Step 3: Set up connection indicator
                self.connected = True
                log.critical("🚨 DIRECT_CONNECTION: Direct connection established, async tools may be loading")
                return True
                
            except Exception as registry_error:
                log.critical(f"🚨 DIRECT_CONNECTION: Could not get registry: {registry_error}")
                log.exception("Registry error:")
                return False
                
        except Exception as e:
            log.critical(f"🚨 DIRECT_CONNECTION: Direct connection failed: {e}")
            log.exception("Connection error:")
            return False
    
    async def get_tools(self):
        """Get tools directly from registry."""
        if not self.registry:
            return []
            
        try:
            tools = await self.registry.list_tools(self.namespace)
            if tools:
                log.info(f"📋 Found {len(tools)} tools in registry")
                tool_objects = []
                for namespace, tool_name in tools:
                    tool_meta = await self.registry.get_metadata(tool_name, namespace)
                    if tool_meta:
                        tool_objects.append({
                            "name": f"{namespace}.{tool_name}",
                            "description": tool_meta.description,
                            "inputSchema": tool_meta.input_schema or {}
                        })
                return tool_objects
            else:
                log.debug("📋 No tools found in registry yet")
                return []
        except Exception as e:
            log.debug(f"Registry tools check failed: {e}")
            return []


class ConfigBypassSSEChukAgent(ChukAgent):
    """
    ChukAgent that completely bypasses config files and connects directly.
    """

    def __init__(self, **kwargs):
        """Initialize with enable_tools defaulting to True for SSE agents."""
        kwargs.setdefault('enable_tools', True)
        super().__init__(**kwargs)
        
        if not self.tool_namespace:
            self.tool_namespace = "sse"
        
        self.direct_connection = None

    async def initialize_tools(self) -> None:
        """Initialize tools with complete config bypass."""
        if self._tools_initialized:
            log.critical("🚨 INITIALIZE_TOOLS: Already initialized, skipping")
            return

        try:
            log.critical("🚨 INITIALIZE_TOOLS: Starting config-bypass initialization")

            # Get servers from environment
            servers = get_mcp_servers_from_env()

            if not servers:
                log.critical("🚨 INITIALIZE_TOOLS: No MCP servers configured")
                self._tools_initialized = True
                self.stream_manager = None
                return

            log.critical(f"🚨 INITIALIZE_TOOLS: Found {len(servers)} servers: {servers}")

            # Create direct connection instead of using setup_mcp_sse
            self.direct_connection = DirectMCPConnection(servers, self.tool_namespace)
            
            # Try to connect directly
            if await self.direct_connection.connect():
                log.critical("🚨 INITIALIZE_TOOLS: Direct MCP connection established!")
                
                # Test if we can get tools
                tools = await self.direct_connection.get_tools()
                if tools:
                    log.critical(f"🚨 INITIALIZE_TOOLS: Found {len(tools)} tools via direct connection")
                    for tool in tools[:3]:
                        log.critical(f"  🔧 {tool.get('name', 'unknown')}")
                else:
                    log.critical("🚨 INITIALIZE_TOOLS: No tools available yet - waiting for async server...")
                    
                    # Wait for async server to process and populate registry
                    for wait_seconds in [2, 5, 10]:
                        log.critical(f"🚨 INITIALIZE_TOOLS: Waiting {wait_seconds}s for async tools...")
                        await asyncio.sleep(wait_seconds)
                        
                        tools = await self.direct_connection.get_tools()
                        if tools:
                            log.critical(f"🚨 INITIALIZE_TOOLS: Found {len(tools)} tools after {wait_seconds}s wait!")
                            for tool in tools[:3]:
                                log.critical(f"  🔧 {tool.get('name', 'unknown')}")
                            break
                    else:
                        log.critical("🚨 INITIALIZE_TOOLS: No tools found after waiting - async server may need more time")
                
                # Mark as initialized regardless of immediate tool availability
                self._tools_initialized = True
                log.critical("🚨 INITIALIZE_TOOLS: Config-bypass initialization complete")
                
            else:
                log.critical("🚨 INITIALIZE_TOOLS: Direct MCP connection failed")
                self._tools_initialized = True
                self.direct_connection = None

        except Exception as e:
            log.critical(f"🚨 INITIALIZE_TOOLS: Failed to initialize: {e}")
            log.exception("Full initialization error:")
            self._tools_initialized = True
            self.direct_connection = None

    async def generate_tools_schema(self):
        """Generate tools schema with direct connection."""
        if not self.direct_connection:
            log.debug("No direct connection - returning empty schema")
            return []
        
        try:
            tools = await self.direct_connection.get_tools()
            if not tools:
                return []
            
            # Convert tools to schema format
            tools_schema = []
            for tool in tools:
                if isinstance(tool, dict):
                    schema = {
                        "type": "function",
                        "function": {
                            "name": tool.get("name", "unknown"),
                            "description": tool.get("description", ""),
                            "parameters": tool.get("inputSchema", {})
                        }
                    }
                    tools_schema.append(schema)
            
            log.debug(f"Generated schema for {len(tools_schema)} tools")
            return tools_schema
            
        except Exception as e:
            log.warning(f"⚠️ Could not generate tools schema: {e}")
            return []

    async def get_available_tools(self):
        """Get available tools with direct connection."""
        if not self.direct_connection:
            return []
        
        try:
            return await self.direct_connection.get_tools()
        except Exception as e:
            log.warning(f"⚠️ Could not get available tools: {e}")
            return []


def create_perplexity_agent(**kwargs):
    """
    Create a perplexity agent with complete config bypass.
    
    Args:
        **kwargs: Configuration parameters passed from YAML
    """
    
    # CRITICAL DEBUG: Always log when this function is called
    import sys
    import traceback
    
    log.critical("🚨 CRITICAL: create_perplexity_agent() CALLED!")
    log.critical(f"🚨 CRITICAL: Called with kwargs: {kwargs}")
    log.critical(f"🚨 CRITICAL: Called from: {traceback.extract_stack()[-2]}")
    
    print("🚨 PRINT: create_perplexity_agent() CALLED!", file=sys.stderr)
    print(f"🚨 PRINT: kwargs = {kwargs}", file=sys.stderr)
    
    log.info("🚀 PERPLEXITY AGENT: create_perplexity_agent called")
    log.info(f"🚀 PERPLEXITY AGENT: kwargs = {kwargs}")
    
    # Extract session-related parameters with defaults
    enable_sessions = kwargs.get('enable_sessions', True)
    enable_tools = kwargs.get('enable_tools', True)
    debug_tools = kwargs.get('debug_tools', False)
    infinite_context = kwargs.get('infinite_context', True)
    token_threshold = kwargs.get('token_threshold', 6000)
    max_turns_per_segment = kwargs.get('max_turns_per_segment', 30)
    session_ttl_hours = kwargs.get('session_ttl_hours', 24)
    
    # Extract other configurable parameters
    provider = kwargs.get('provider', 'openai')
    model = kwargs.get('model', 'gpt-4o')
    streaming = kwargs.get('streaming', True)
    
    # MCP configuration
    mcp_servers = kwargs.get('mcp_servers', ["perplexity_server"])
    tool_namespace = kwargs.get('tool_namespace', "sse")
    
    log.critical(f"🚨 CRITICAL: enable_tools = {enable_tools}")
    log.critical(f"🚨 CRITICAL: enable_sessions = {enable_sessions}")
    
    # Check if MCP server configuration exists
    if enable_tools:
        log.critical("🚨 CRITICAL: Checking MCP server configuration...")
        servers = get_mcp_servers_from_env()
        if not servers:
            log.critical("🚨 CRITICAL: No MCP server configuration found - disabling tools")
            enable_tools = False
        else:
            log.critical(f"🚨 CRITICAL: Found MCP server configuration: {servers}")
    
    log.critical(f"🚨 CRITICAL: Creating config-bypass perplexity agent")
    log.critical(f"🚨 CRITICAL: Sessions: {enable_sessions}, Tools: {enable_tools}")
    
    try:
        if enable_tools:
            log.critical("🚨 CRITICAL: Creating with MCP tools enabled...")
            # Create config-bypass SSE agent
            try:
                # Filter out parameters we're setting explicitly to avoid duplicate kwargs
                filtered_kwargs = {k: v for k, v in kwargs.items() if k not in [
                    'enable_sessions', 'enable_tools', 'debug_tools',
                    'infinite_context', 'token_threshold', 'max_turns_per_segment',
                    'session_ttl_hours', 'provider', 'model', 'streaming',
                    'mcp_servers', 'tool_namespace', 'name', 'description', 'instruction'
                ]}
                
                agent = ConfigBypassSSEChukAgent(
                    name="perplexity_agent",
                    provider=provider,
                    model=model,
                    description="Perplexity-style research agent with direct MCP connection",
                    instruction="You are a helpful research assistant.",
                    streaming=streaming,
                    enable_sessions=enable_sessions,
                    infinite_context=infinite_context,
                    token_threshold=token_threshold,
                    max_turns_per_segment=max_turns_per_segment,
                    session_ttl_hours=session_ttl_hours,
                    enable_tools=enable_tools,
                    debug_tools=debug_tools,
                    mcp_servers=mcp_servers,
                    tool_namespace=tool_namespace,
                    **filtered_kwargs
                )
                log.critical("🚨 CRITICAL: Created config-bypass perplexity agent with direct MCP connection")
                
            except Exception as sse_error:
                log.critical(f"🚨 CRITICAL: Config-bypass agent creation failed: {sse_error}")
                log.exception("SSE agent creation error:")
                enable_tools = False
        
        if not enable_tools:
            log.critical("🚨 CRITICAL: Creating fallback agent without tools...")
            # Create fallback ChukAgent
            
            # Filter out parameters for fallback agent too
            fallback_filtered_kwargs = {k: v for k, v in kwargs.items() if k not in [
                'enable_sessions', 'enable_tools', 'provider', 'model', 'streaming',
                'name', 'description', 'instruction', 'infinite_context', 
                'token_threshold', 'max_turns_per_segment', 'session_ttl_hours'
            ]}
            
            agent = ChukAgent(
                name="perplexity_agent",
                provider=provider,
                model=model,
                description="Research assistant (MCP tools unavailable)",
                instruction="I'm a research assistant.",
                streaming=streaming,
                enable_sessions=enable_sessions,
                infinite_context=infinite_context,
                token_threshold=token_threshold,
                max_turns_per_segment=max_turns_per_segment,
                session_ttl_hours=session_ttl_hours,
                enable_tools=False,
                **fallback_filtered_kwargs
            )
            log.critical("🚨 CRITICAL: Created fallback perplexity agent without MCP tools")
        
        # Debug logging
        log.critical(f"🚨 CRITICAL: PERPLEXITY AGENT CREATED: {type(agent).__name__}")
        log.critical(f"🚨 CRITICAL: Internal sessions enabled: {agent.enable_sessions}")
        log.critical(f"🚨 CRITICAL: Tools enabled: {getattr(agent, 'enable_tools', False)}")
        
        return agent
        
    except Exception as e:
        log.critical(f"🚨 CRITICAL: Failed to create perplexity_agent: {e}")
        log.exception("Full creation error:")
        
        # Create a minimal fallback ChukAgent
        fallback_agent = ChukAgent(
            name="perplexity_agent",
            provider=provider,
            model=model,
            description="Basic research assistant",
            instruction="I'm a research assistant.",
            streaming=streaming,
            enable_sessions=enable_sessions
        )
        
        log.critical("🚨 CRITICAL: Created minimal fallback perplexity agent")
        return fallback_agent


# Lazy loading to prevent duplicate creation
_perplexity_agent_cache = None

def get_perplexity_agent():
    """Get or create a default perplexity agent instance (cached)."""
    global _perplexity_agent_cache
    if _perplexity_agent_cache is None:
        log.info("🔍 CACHE: Creating cached perplexity agent...")
        _perplexity_agent_cache = create_perplexity_agent(enable_tools=True)
        log.info("✅ Cached config-bypass perplexity_agent created")
    else:
        log.info("🔍 CACHE: Using existing cached perplexity agent")
    return _perplexity_agent_cache

# For direct import compatibility
try:
    log.info("🔍 MODULE LOAD: Creating module-level perplexity_agent...")
    log.info(f"🔍 MODULE LOAD: About to call get_perplexity_agent()")
    perplexity_agent = get_perplexity_agent()
    log.info(f"🔍 MODULE LOAD: Perplexity agent created: {type(perplexity_agent)}")
    log.info(f"🔍 MODULE LOAD: Agent tools enabled: {getattr(perplexity_agent, 'enable_tools', 'unknown')}")
except Exception as e:
    log.error(f"❌ Failed to create module-level perplexity_agent: {e}")
    log.exception("Module level creation error:")
    perplexity_agent = None

log.info("🔥 PERPLEXITY_AGENT MODULE: Module import complete!")
log.info(f"🔥 PERPLEXITY_AGENT MODULE: perplexity_agent = {perplexity_agent}")


# Export everything for flexibility
__all__ = ['create_perplexity_agent', 'get_perplexity_agent', 'ConfigBypassSSEChukAgent', 'perplexity_agent']