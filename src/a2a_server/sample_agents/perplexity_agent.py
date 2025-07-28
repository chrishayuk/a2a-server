# a2a_server/sample_agents/perplexity_agent.py
"""
Perplexity Agent - Research assistant with MCP tools via standard tool processor
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

log = logging.getLogger(__name__)

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
    """Get MCP server configuration from environment variables for SSE transport."""
    
    log.debug("Checking SSE MCP environment variables...")
    log.debug(f"MCP_SERVER_URL: {os.getenv('MCP_SERVER_URL', 'NOT SET')}")
    log.debug(f"MCP_SERVER_URL_MAP: {os.getenv('MCP_SERVER_URL_MAP', 'NOT SET')}")
    log.debug(f"MCP_SERVER_NAME_MAP: {os.getenv('MCP_SERVER_NAME_MAP', 'NOT SET')}")
    log.debug(f"MCP_BEARER_TOKEN: {'SET' if os.getenv('MCP_BEARER_TOKEN') else 'NOT SET'}")
    
    token = os.getenv("MCP_BEARER_TOKEN")
    
    def make_entry(name: str, url: str) -> Dict[str, str]:
        entry = {"name": name, "url": url}
        if token:
            entry["api_key"] = token
        return entry

    name_override = _load_override("MCP_SERVER_NAME_MAP")
    url_override = _load_override("MCP_SERVER_URL_MAP")
    
    if single_server_url := os.getenv("MCP_SERVER_URL"):
        log.info(f"Using single SSE MCP server: {single_server_url}")
        return [make_entry("perplexity_server", single_server_url)]
    
    if url_override:
        servers = []
        for srv_name, srv_url in url_override.items():
            actual = name_override.get(srv_name, srv_name)
            servers.append(make_entry(actual, srv_url))
        log.info(f"Using {len(servers)} SSE MCP server(s) from URL map")
        return servers
    
    log.debug("No SSE MCP server configuration found in environment variables")
    return []

# Removed _create_perplexity_mcp_config function - not needed for SSE transport

def create_perplexity_agent(**kwargs):
    """
    Create a perplexity agent with standard MCP integration.
    
    Args:
        **kwargs: Configuration parameters passed from YAML
    """
    
    log.debug("Creating perplexity agent...")
    log.debug(f"Configuration: {kwargs}")
    
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
    
    # MCP configuration (removed - SSE transport uses env vars directly)
    tool_namespace = kwargs.get('tool_namespace', "sse")
    
    log.info(f"🔍 Creating perplexity agent with sessions: {enable_sessions}")
    log.info(f"🔍 Using model: {provider}/{model}")
    log.info(f"🔍 MCP tools enabled: {enable_tools}")
    
    # Check if SSE MCP server configuration exists
    sse_servers = []
    if enable_tools:
        sse_servers = get_mcp_servers_from_env()
        if not sse_servers:
            log.warning("No SSE MCP server configuration found - tools will be disabled")
            log.info("To enable tools, set environment variables:")
            log.info("  export MCP_SERVER_URL='https://your-server.com'")
            log.info("  export MCP_BEARER_TOKEN='your-token'")
            enable_tools = False
        else:
            log.debug(f"Found SSE server configuration: {sse_servers}")
    
    # Skip config file creation for SSE transport - use environment variables directly
    if enable_tools and sse_servers:
        log.info(f"🔍 Using SSE transport with {len(sse_servers)} servers - skipping config file creation")
    
    try:
        if enable_tools and sse_servers:
            # Create agent with MCP SSE tools using standard ChukAgent
            try:
                # Filter out parameters we're setting explicitly
                filtered_kwargs = {k: v for k, v in kwargs.items() if k not in [
                    'enable_sessions', 'enable_tools', 'debug_tools',
                    'infinite_context', 'token_threshold', 'max_turns_per_segment',
                    'session_ttl_hours', 'provider', 'model', 'streaming',
                    'mcp_config_file', 'mcp_servers', 'tool_namespace'
                ]}
                
                agent = ChukAgent(
                    name="perplexity_agent",
                    provider=provider,
                    model=model,
                    description="Perplexity-style research agent with SSE MCP integration",
                    instruction="""You are a helpful research assistant with access to powerful search and research tools.

🔍 AVAILABLE TOOLS:
You have access to research tools that can help you find current, accurate information on any topic.

When users ask questions:
1. Use your research tools to find up-to-date, accurate information
2. Provide comprehensive, well-sourced answers
3. Cite your sources when possible
4. If you can't find information through tools, explain what you searched for
5. Offer to search with different terms or approaches if initial searches don't yield results

Always prioritize accuracy and recency of information. Use your tools proactively to provide the most helpful and current responses possible.""",
                    streaming=streaming,
                    
                    # Session management
                    enable_sessions=enable_sessions,
                    infinite_context=infinite_context,
                    token_threshold=token_threshold,
                    max_turns_per_segment=max_turns_per_segment,
                    session_ttl_hours=session_ttl_hours,
                    
                    # MCP tools - using SSE transport (no config file needed)
                    enable_tools=enable_tools,
                    debug_tools=debug_tools,
                    mcp_transport="sse",  # Use SSE transport for remote servers
                    mcp_sse_servers=sse_servers,  # Pass SSE server configuration directly
                    tool_namespace=tool_namespace,
                    
                    # Pass through any other kwargs
                    **filtered_kwargs
                )
                
                log.info("🔍 Perplexity agent created successfully with SSE MCP tools")
                return agent
                
            except Exception as mcp_error:
                log.warning(f"🔍 SSE MCP initialization failed: {mcp_error}")
                log.info("🔍 Creating fallback agent without MCP tools")
                enable_tools = False
        
        if not enable_tools:
            # Create fallback ChukAgent without tools
            fallback_filtered_kwargs = {k: v for k, v in kwargs.items() if k not in [
                'enable_sessions', 'enable_tools', 'provider', 'model', 'streaming',
                'infinite_context', 'token_threshold', 'max_turns_per_segment', 
                'session_ttl_hours', 'mcp_config_file', 'mcp_servers', 'tool_namespace'
            ]}
            
            agent = ChukAgent(
                name="perplexity_agent",
                provider=provider,
                model=model,
                description="Research assistant (SSE MCP tools unavailable)",
                instruction="""I'm a research assistant with comprehensive knowledge to help answer your questions.

🧠 KNOWLEDGE-BASED ASSISTANCE:
While my real-time research tools are currently unavailable, I can still help with:
✅ General knowledge questions
✅ Analysis and explanation of topics
✅ Research methodology and approaches
✅ Connecting related concepts and ideas
✅ Providing context and background information

📝 Note: My real-time research tools are temporarily unavailable. 
To enable them, ensure your MCP server environment variables are configured:
   export MCP_SERVER_URL='https://your-research-server.com'
   export MCP_BEARER_TOKEN='your-token'

I'll do my best to provide helpful information based on my training data.""",
                streaming=streaming,
                
                # Session management
                enable_sessions=enable_sessions,
                infinite_context=infinite_context,
                token_threshold=token_threshold,
                max_turns_per_segment=max_turns_per_segment,
                session_ttl_hours=session_ttl_hours,
                
                # No tools
                enable_tools=False,
                
                **fallback_filtered_kwargs
            )
            log.info("🔍 Created fallback perplexity agent without SSE MCP tools")
        
        log.info(f"Perplexity agent created: {type(agent).__name__}")
        return agent
        
    except Exception as e:
        log.error(f"Failed to create perplexity_agent: {e}")
        log.exception("Perplexity agent creation error:")
        
        # Create a minimal fallback ChukAgent
        fallback_agent = ChukAgent(
            name="perplexity_agent",
            provider=provider,
            model=model,
            description="Basic research assistant",
            instruction="I'm a research assistant. I can help with general questions based on my training.",
            streaming=streaming,
            enable_sessions=enable_sessions,
            enable_tools=False
        )
        
        log.info("Created minimal fallback perplexity agent")
        return fallback_agent

# Lazy loading to prevent duplicate creation
_perplexity_agent_cache = None

def get_perplexity_agent():
    """Get or create a default perplexity agent instance (cached)."""
    global _perplexity_agent_cache
    if _perplexity_agent_cache is None:
        log.debug("Creating cached perplexity agent...")
        _perplexity_agent_cache = create_perplexity_agent(enable_tools=True)
        log.info("✅ Cached perplexity_agent created")
    else:
        log.debug("Using existing cached perplexity agent")
    return _perplexity_agent_cache

# For direct import compatibility
try:
    log.debug("Creating module-level perplexity_agent...")
    perplexity_agent = get_perplexity_agent()
    log.debug(f"Perplexity agent created: {type(perplexity_agent)}")
    log.debug(f"Agent tools enabled: {getattr(perplexity_agent, 'enable_tools', 'unknown')}")
except Exception as e:
    log.error(f"❌ Failed to create module-level perplexity_agent: {e}")
    log.exception("Module level creation error:")
    # Create a minimal fallback to ensure the import works
    perplexity_agent = ChukAgent(
        name="perplexity_agent",
        provider="openai", 
        model="gpt-4o",
        description="Basic research assistant (fallback)",
        instruction="I'm a research assistant.",
        enable_tools=False
    )
    log.info("Created emergency fallback perplexity agent")

log.debug("Perplexity agent module loading complete")

# Export everything for flexibility
__all__ = ['create_perplexity_agent', 'get_perplexity_agent', 'perplexity_agent']