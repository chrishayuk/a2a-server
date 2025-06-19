# a2a_server/sample_agents/weather_agent.py
"""
Weather Agent - Assistant with weather capabilities via MCP
"""
import json
import logging
from pathlib import Path
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

# Create the configuration for the weather MCP server
config_file = "weather_server_config.json"
config = {
    "mcpServers": {
        "weather": {
            "command": "uvx",
            "args": ["mcp-server-weather"]
        }
    }
}

# Ensure config file exists and is updated
config_path = Path(config_file)
config_path.write_text(json.dumps(config, indent=2))
logger.info(f"Updated weather MCP config: {config_file}")

try:
    # Weather agent with native MCP integration
    weather_agent = ChukAgent(
        name="weather_agent",
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
        provider="openai", 
        model="gpt-4o-mini",
        mcp_transport="stdio",
        mcp_config_file=config_file,
        mcp_servers=["weather"],
        namespace="stdio"
    )
    logger.info("Weather agent created successfully with MCP tools")
    
except Exception as e:
    logger.error(f"Failed to create weather agent with MCP: {e}")
    logger.error("Make sure to install: uvx install mcp-server-weather")
    
    # Fallback agent with clear error message
    weather_agent = ChukAgent(
        name="weather_agent",
        description="Weather assistant (tools unavailable - check setup)",
        instruction="""I'm a weather assistant, but my weather data tools are currently unavailable.

In the meantime, I recommend checking:
- weather.com
- weather.gov
- Your local weather app

I apologize for the inconvenience!""",
        provider="openai",
        model="gpt-4o-mini",
        mcp_transport="stdio",
        mcp_servers=[],  # No MCP servers for fallback
        namespace="stdio"
    )
    logger.warning("Created fallback weather agent - MCP tools unavailable")