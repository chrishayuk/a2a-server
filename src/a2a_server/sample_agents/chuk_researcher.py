# a2a_server/sample_agents/chuk_researcher.py
"""
Research agent with MCP-based search capabilities.
"""
import json
import logging
from pathlib import Path
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

# Create configuration for search MCP servers
config_file = "research_server_config.json"
config = {
    "mcpServers": {
        "brave_search": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-brave-search"],
            "env": {
                "BRAVE_API_KEY": "${BRAVE_API_KEY}"
            }
        },
        "wikipedia": {
            "command": "python",
            "args": ["-m", "mcp_server_wikipedia"],
            "description": "Wikipedia search and lookup"
        }
    }
}

# Ensure config file exists
config_path = Path(config_file)
config_path.write_text(json.dumps(config, indent=2))
logger.info(f"Created research MCP config: {config_file}")

try:
    # Research agent with MCP search tools
    research_agent = ChukAgent(
        name="research_agent",
        description="Research assistant with web search and Wikipedia capabilities",
        instruction="""You are a Research Assistant specialized in finding and synthesizing information.

🔍 AVAILABLE TOOLS:
- Web search capabilities via Brave Search
- Wikipedia lookup for encyclopedic information
- Fact-checking and verification tools

RESEARCH METHODOLOGY:
1. When asked questions, use your tools to gather relevant information
2. Search multiple sources when possible for comprehensive coverage
3. Cross-reference information between web search and Wikipedia
4. Always cite your sources when providing information
5. Structure complex answers with clear headings and organization

RESPONSE GUIDELINES:
- Start with a brief summary/answer
- Provide detailed information with proper citations
- Use bullet points or numbered lists for clarity
- Include relevant links when available
- Acknowledge limitations or conflicting information
- Suggest follow-up questions for deeper research

SEARCH STRATEGY:
- Use specific, targeted search terms
- Search for recent information when currency matters
- Use Wikipedia for background/foundational information
- Verify facts across multiple sources when possible

Always strive for accuracy, comprehensiveness, and clarity in your research.""",
        provider="openai",
        model="gpt-4o",  # Using more capable model for research
        mcp_transport="stdio",
        mcp_config_file=config_file,
        mcp_servers=["brave_search", "wikipedia"],
        namespace="stdio"
    )
    logger.info("Research agent created successfully with MCP search tools")
    
except Exception as e:
    logger.error(f"Failed to create research agent with MCP: {e}")
    logger.error("Make sure to set BRAVE_API_KEY environment variable")
    
    # Fallback research agent without tools
    research_agent = ChukAgent(
        name="research_agent",
        description="Research assistant (search tools unavailable)",
        instruction="""I'm a research assistant, but my search tools are currently unavailable""",
        provider="openai",
        model="gpt-4o"
    )
    logger.warning("Created fallback research agent - MCP search tools unavailable")