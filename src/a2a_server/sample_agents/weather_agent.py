# a2a_server/sample_agents/weather_agent.py
"""
Weather Agent - Assistant with weather capabilities via MCP
FIXED VERSION: Proper factory function, API key handling, no duplicate creation
"""
import json
import logging
import os
from pathlib import Path
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

def create_weather_agent(**kwargs):
    """
    Create a weather agent with configurable parameters.
    
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
    config_file = kwargs.get('mcp_config_file', "weather_server_config.json")
    mcp_servers = kwargs.get('mcp_servers', ["weather"])
    weather_api_key = kwargs.get('weather_api_key') or os.getenv('WEATHER_API_KEY')
    
    logger.info(f"🌦️ Creating weather agent with sessions: {enable_sessions}")
    logger.info(f"🌦️ Using model: {provider}/{model}")
    logger.info(f"🌦️ MCP tools enabled: {enable_tools}")
    logger.info(f"🌦️ Weather API key: {'SET' if weather_api_key else 'NOT SET'}")
    
    # Check for API key requirement
    if enable_tools and not weather_api_key:
        logger.warning("🌦️ Weather API key not found - disabling MCP tools")
        logger.info("💡 Set WEATHER_API_KEY environment variable or pass weather_api_key parameter")
        enable_tools = False
    
    # Create MCP configuration if tools are enabled
    if enable_tools:
        try:
            _create_weather_mcp_config(config_file, weather_api_key)
            logger.info(f"🌦️ MCP configuration created: {config_file}")
        except Exception as e:
            logger.warning(f"Failed to create weather MCP config: {e}")
            enable_tools = False
    
    try:
        if enable_tools:
            # Try to create with MCP tools
            try:
                agent = ChukAgent(
                    name="weather_agent",
                    provider=provider,
                    model=model,
                    description="Assistant with weather forecasting capabilities via native MCP integration",
                    instruction="""You are a helpful weather assistant with access to real weather data through MCP tools.

🌦️ AVAILABLE TOOLS:
- get_weather(location: str) - Get current weather for any city/location
- get_forecast(location: str, days: int) - Get weather forecast  
- get_historical_weather(location: str, date: str) - Get historical weather data

When users ask about weather:
1. ALWAYS use your tools to get real, current weather data
2. For current weather: call get_weather("City Name")
3. For forecasts: call get_forecast("City Name", days)
4. Provide specific details: temperature, conditions, humidity, wind, etc.
5. Give helpful context about what the weather means (dress warmly, bring umbrella, etc.)

Examples:
- "Weather in London" → get_weather("London")
- "Forecast for New York" → get_forecast("New York", 5)
- "Weather yesterday in Paris" → get_historical_weather("Paris", "2025-06-17")

IMPORTANT: Always use your tools to get real data. Never give generic responses!""",
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
                        'mcp_config_file', 'mcp_servers', 'weather_api_key'
                    ]}
                )
                logger.info("🌦️ Weather agent created successfully with MCP tools")
                
            except Exception as mcp_error:
                logger.warning(f"🌦️ MCP initialization failed: {mcp_error}")
                logger.info("🌦️ Creating fallback agent without MCP tools")
                enable_tools = False
                
        if not enable_tools:
            # Fallback without tools
            agent = ChukAgent(
                name="weather_agent",
                provider=provider,
                model=model,
                description="Weather assistant (MCP tools unavailable)",
                instruction="""I'm a weather assistant, but my weather data tools are currently unavailable.

🌦️ WEATHER ASSISTANCE:
I can help with general weather information and advice, but I don't have access to real-time weather data.

For current weather conditions, I recommend checking:
- weather.com
- weather.gov  
- Your local weather app
- AccuWeather
- The Weather Channel

I can still help with:
- General weather pattern explanations
- Seasonal weather advice
- Weather preparation tips
- Climate information

💡 To enable real-time weather tools, set up a weather API key:
export WEATHER_API_KEY="your-api-key-here"

I apologize for the inconvenience!""",
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
            logger.info("🌦️ Created fallback weather agent - MCP tools unavailable")
            
    except Exception as e:
        logger.error(f"Failed to create weather agent: {e}")
        logger.error("Creating basic weather agent without tools")
        
        # Basic fallback
        agent = ChukAgent(
            name="weather_agent",
            provider=provider,
            model=model,
            description="Basic weather assistant",
            instruction="I'm a weather assistant. I can help with general weather questions and advice based on my training.",
            streaming=streaming,
            enable_sessions=enable_sessions,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            session_ttl_hours=session_ttl_hours
        )
    
    # Debug logging
    logger.info(f"🌦️ WEATHER AGENT CREATED: {type(agent)}")
    logger.info(f"🌦️ Internal sessions enabled: {agent.enable_sessions}")
    logger.info(f"🌦️ Tools enabled: {getattr(agent, 'enable_tools', False)}")
    
    if enable_sessions:
        logger.info(f"🌦️ Agent will manage weather sessions internally")
    else:
        logger.info(f"🌦️ External sessions will be managed by handler")
    
    return agent


def _create_weather_mcp_config(config_file: str, api_key: str):
    """Create MCP configuration file for weather tools."""
    config = {
        "mcpServers": {
            "weather": {
                "command": "uvx",
                "args": ["mcp-server-weather", "--api_key", api_key],
                "description": "Weather forecasting and current conditions"
            }
        }
    }
    
    # Ensure config file exists
    config_path = Path(config_file)
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2))
        logger.info(f"Created weather MCP config: {config_file}")
        
        # Installation hint
        logger.info("💡 To enable weather tools, install: uvx install mcp-server-weather")
        logger.info("💡 And get a weather API key from OpenWeatherMap or similar service")
        
    except Exception as e:
        logger.error(f"Failed to create MCP config file {config_file}: {e}")
        raise


# 🔧 OPTIMIZED: Lazy loading to prevent duplicate creation
_weather_agent_cache = None

def get_weather_agent():
    """Get or create a default weather agent instance (cached)."""
    global _weather_agent_cache
    if _weather_agent_cache is None:
        _weather_agent_cache = create_weather_agent(enable_tools=False)  # Conservative default
        logger.info("✅ Cached weather_agent created")
    return _weather_agent_cache

# For direct import compatibility, create the instance
try:
    weather_agent = get_weather_agent()
except Exception as e:
    logger.error(f"❌ Failed to create module-level weather_agent: {e}")
    weather_agent = None

# Export everything for flexibility
__all__ = ['create_weather_agent', 'get_weather_agent', 'weather_agent']