# a2a_server/sample_agents/time_agent.py
"""
Time Agent - Assistant with time and timezone capabilities via MCP
OPTIMIZED VERSION: No duplicate agent creation
"""
import json
import logging
from pathlib import Path
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

def create_time_agent(**kwargs):
    """
    Create a time agent with configurable parameters.
    
    Args:
        **kwargs: Configuration parameters passed from YAML
    """
    # Extract session-related parameters with defaults
    enable_sessions = kwargs.get('enable_sessions', False)  # Default to False for utility agents
    enable_tools = kwargs.get('enable_tools', True)         # Default to True for MCP tools
    debug_tools = kwargs.get('debug_tools', False)
    infinite_context = kwargs.get('infinite_context', True)
    token_threshold = kwargs.get('token_threshold', 4000)
    max_turns_per_segment = kwargs.get('max_turns_per_segment', 50)
    session_ttl_hours = kwargs.get('session_ttl_hours', 24)
    
    # Extract other configurable parameters
    provider = kwargs.get('provider', 'openai')
    model = kwargs.get('model', 'gpt-4o-mini')
    streaming = kwargs.get('streaming', True)
    
    # MCP configuration
    config_file = kwargs.get('mcp_config_file', "time_server_config.json")
    mcp_servers = kwargs.get('mcp_servers', ["time"])
    
    logger.info(f"🕒 Creating time agent with sessions: {enable_sessions}")
    logger.info(f"🕒 Using model: {provider}/{model}")
    logger.info(f"🕒 MCP tools enabled: {enable_tools}")
    
    # Create MCP configuration if tools are enabled
    if enable_tools:
        try:
            _create_time_mcp_config(config_file)
            logger.info(f"🕒 MCP configuration created: {config_file}")
        except Exception as e:
            logger.warning(f"Failed to create time MCP config: {e}")
            enable_tools = False
    
    try:
        if enable_tools:
            # Try to create with MCP tools
            try:
                agent = ChukAgent(
                    name="time_agent",
                    provider=provider,
                    model=model,
                    description="Assistant with time and timezone capabilities via native MCP integration",
                    instruction="""You are a helpful time assistant with access to time-related tools.

🕒 AVAILABLE TOOLS:
- get_current_time: Get current time in any timezone using IANA timezone names
- convert_time: Convert between timezones

When users ask about time:
1. Use your time tools to provide accurate, real-time information
2. For get_current_time, always provide the timezone parameter using IANA timezone names
3. Common timezone mappings:
   - New York: America/New_York
   - Los Angeles: America/Los_Angeles
   - London: Europe/London
   - Tokyo: Asia/Tokyo
   - Paris: Europe/Paris
4. If user asks for a city time, convert the city to the appropriate IANA timezone
5. Explain timezone differences when relevant
6. Help with scheduling across timezones
7. Provide clear, helpful time-related advice

Always be precise with time information and explain any calculations you perform.""",
                    streaming=streaming,
                    
                    # Session management
                    enable_sessions=enable_sessions,
                    infinite_context=infinite_context,
                    token_threshold=token_threshold,
                    max_turns_per_segment=max_turns_per_segment,
                    session_ttl_hours=session_ttl_hours,
                    
                    # MCP tools
                    enable_tools=enable_tools,
                    debug_tools=debug_tools,
                    mcp_transport="stdio",
                    mcp_config_file=config_file,
                    mcp_servers=mcp_servers,
                    namespace="stdio",
                    
                    # Pass through any other kwargs
                    **{k: v for k, v in kwargs.items() if k not in [
                        'enable_sessions', 'enable_tools', 'debug_tools',
                        'infinite_context', 'token_threshold', 'max_turns_per_segment',
                        'session_ttl_hours', 'provider', 'model', 'streaming',
                        'mcp_config_file', 'mcp_servers'
                    ]}
                )
                logger.info("🕒 Time agent created successfully with MCP tools")
                
            except Exception as mcp_error:
                logger.warning(f"🕒 MCP initialization failed: {mcp_error}")
                logger.info("🕒 Creating fallback agent without MCP tools")
                enable_tools = False
                
        if not enable_tools:
            # Fallback without tools
            agent = ChukAgent(
                name="time_agent",
                provider=provider,
                model=model,
                description="Time assistant (MCP tools unavailable)",
                instruction="""I'm a time assistant with comprehensive timezone knowledge.

🌍 TIMEZONE EXPERTISE:
- New York: America/New_York (EST/EDT, UTC-5/-4)
- Los Angeles: America/Los_Angeles (PST/PDT, UTC-8/-7)  
- London: Europe/London (GMT/BST, UTC+0/+1)
- Paris: Europe/Paris (CET/CEST, UTC+1/+2)
- Tokyo: Asia/Tokyo (JST, UTC+9)
- Sydney: Australia/Sydney (AEST/AEDT, UTC+10/+11)

I can help with:
- General time zone information and conversions
- Scheduling advice across timezones
- Time-related calculations
- Business hours in different regions

Note: For precise current times, I recommend checking your system clock or timeanddate.com as my real-time tools are temporarily unavailable.""",
                streaming=streaming,
                
                # Session management
                enable_sessions=enable_sessions,
                infinite_context=infinite_context,
                token_threshold=token_threshold,
                max_turns_per_segment=max_turns_per_segment,
                session_ttl_hours=session_ttl_hours,
                
                # Pass through any other kwargs
                **{k: v for k, v in kwargs.items() if k not in [
                    'enable_sessions', 'infinite_context', 'token_threshold',
                    'max_turns_per_segment', 'session_ttl_hours', 'provider',
                    'model', 'streaming'
                ]}
            )
            logger.info("🕒 Created fallback time agent - MCP tools unavailable")
            
    except Exception as e:
        logger.error(f"Failed to create time agent: {e}")
        logger.error("Creating basic time agent without tools")
        
        # Basic fallback
        agent = ChukAgent(
            name="time_agent",
            provider=provider,
            model=model,
            description="Basic time assistant",
            instruction="I'm a time assistant. I can help with general time-related questions and advice based on my training.",
            streaming=streaming,
            enable_sessions=enable_sessions,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            session_ttl_hours=session_ttl_hours
        )
    
    # Debug logging
    logger.info(f"🕒 TIME AGENT CREATED: {type(agent)}")
    logger.info(f"🕒 Internal sessions enabled: {agent.enable_sessions}")
    logger.info(f"🕒 Tools enabled: {getattr(agent, 'enable_tools', False)}")
    
    if enable_sessions:
        logger.info(f"🕒 Agent will manage time sessions internally")
    else:
        logger.info(f"🕒 External sessions will be managed by handler")
    
    return agent


def _create_time_mcp_config(config_file: str):
    """Create MCP configuration file for time tools."""
    config = {
        "mcpServers": {
            "time": {
                "command": "uvx",
                "args": ["mcp-server-time", "--local-timezone=America/New_York"],
                "description": "Time and timezone utilities"
            }
        }
    }
    
    # Ensure config file exists
    config_path = Path(config_file)
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2))
        logger.info(f"Created time MCP config: {config_file}")
        
        # Installation hint
        logger.info("💡 To enable time tools, install: uvx install mcp-server-time")
        
    except Exception as e:
        logger.error(f"Failed to create MCP config file {config_file}: {e}")
        raise


# 🔧 OPTIMIZED: Lazy loading to prevent duplicate creation
_time_agent_cache = None

def get_time_agent():
    """Get or create a default time agent instance (cached)."""
    global _time_agent_cache
    if _time_agent_cache is None:
        _time_agent_cache = create_time_agent(enable_tools=False)  # Conservative default
        logger.info("✅ Cached time_agent created")
    return _time_agent_cache

# 🔧 OPTIMIZED: Create module-level agent only when accessed
@property
def time_agent():
    """Module-level time agent instance (lazy loaded)."""
    return get_time_agent()

# For direct import compatibility, create the instance
try:
    time_agent = get_time_agent()
except Exception as e:
    logger.error(f"❌ Failed to create module-level time_agent: {e}")
    time_agent = None

# Export everything for flexibility
__all__ = ['create_time_agent', 'get_time_agent', 'time_agent']