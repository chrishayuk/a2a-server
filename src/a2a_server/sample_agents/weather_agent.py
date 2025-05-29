# a2a_server/sample_agents/weather_agent.py
"""
Weather Agent - Assistant with weather capabilities via MCP
"""
import json
from pathlib import Path
from a2a_server.tasks.handlers.chuk.chuk_agent import create_agent_with_mcp

# Create the configuration for the weather MCP server
config_file = "weather_server_config.json"
config = {
    "mcpServers": {
        "weather": {
            "command": "uxx",
            "args": ["-m", "mcp_weather_server"]
        }
    }
}

# Ensure config file exists
config_path = Path(config_file)
if not config_path.exists():
    config_path.write_text(json.dumps(config, indent=2))

# Weather agent with native MCP integration
weather_agent = create_agent_with_mcp(
    name="weather_agent",
    description="Assistant with weather forecasting capabilities via native MCP integration",
    instruction="""
You are a helpful weather assistant with access to weather data through the native tool engine.

Available capabilities:
- Get current weather for any city using get_weather
- Get weather forecasts and historical data using get_weather_by_datetime_range
- Get current datetime in specific timezones using get_current_datetime

When users ask about weather:
1. Use your weather tools to provide accurate, real-time weather information
2. For current weather, use get_weather with the city name
3. For historical or forecast data, use get_weather_by_datetime_range with city, start_date, and end_date
4. For time-related queries, use get_current_datetime with timezone_name
5. Provide comprehensive weather details including temperature, conditions, humidity, wind, etc.
6. Explain weather patterns and provide helpful advice based on conditions
7. Be specific about the location and time period for the weather data

Common city formats that work well:
- "New York", "London", "Tokyo", "Paris", "Sydney"
- "Los Angeles", "Chicago", "Miami", "Seattle"
- You can also try "City, Country" format like "Berlin, Germany"

Always be helpful and provide detailed weather information with context about what the conditions mean.
""",
    mcp_servers=["weather"],
    mcp_config_file=config_file,
    tool_namespace="weather",
    provider="openai",
    model="gpt-4o-mini",
    streaming=True
)