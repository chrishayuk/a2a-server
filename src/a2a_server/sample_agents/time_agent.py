# a2a_server/sample_agents/time_agent.py
"""
Time Agent - Assistant with time and timezone capabilities via MCP
"""
import json
from pathlib import Path
from a2a_server.tasks.handlers.chuk.chuk_agent import create_agent_with_mcp

# Create the configuration for the time MCP server
config_file = "time_server_config.json"
config = {
    "mcpServers": {
        "time": {
            "command": "uvx",
            "args": ["mcp-server-time", "--local-timezone=America/New_York"]
        }
    }
}

# Ensure config file exists
config_path = Path(config_file)
if not config_path.exists():
    config_path.write_text(json.dumps(config, indent=2))

# Time agent with native MCP integration - Fixed configuration
time_agent = create_agent_with_mcp(
    name="time_agent",
    description="Assistant with time and timezone capabilities via native MCP integration",
    instruction="""
You are a helpful time assistant with access to time-related tools through the native tool engine.

Available capabilities:
- Get current time in any timezone using get_current_time
- Convert between timezones using convert_time
- Time calculations and scheduling assistance

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

Always be precise with time information and explain any calculations you perform.
""",
    mcp_servers=["time"],
    mcp_config_file=config_file,
    tool_namespace="time",  # Use a proper namespace string instead of empty string
    provider="openai",
    model="gpt-4o-mini",
    streaming=True
)