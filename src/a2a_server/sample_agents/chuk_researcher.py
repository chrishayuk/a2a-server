# a2a_server/sample_agents/chuk_researcher.py
"""
Research agent with MCP-based search capabilities and configurable session management.
"""
import json
import logging
import os
from pathlib import Path
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

def create_research_agent(**kwargs):
    """
    Create a research agent with configurable parameters and MCP search tools.
    
    Args:
        **kwargs: Configuration parameters passed from YAML
    """
    # Extract session-related parameters with defaults
    enable_sessions = kwargs.get('enable_sessions', True)  # Default to True for research continuity
    enable_tools = kwargs.get('enable_tools', True)        # Default to True for MCP tools
    debug_tools = kwargs.get('debug_tools', False)
    infinite_context = kwargs.get('infinite_context', True)
    token_threshold = kwargs.get('token_threshold', 8000)  # Higher for research
    max_turns_per_segment = kwargs.get('max_turns_per_segment', 30)
    session_ttl_hours = kwargs.get('session_ttl_hours', 48)  # Longer for research projects
    
    # Extract other configurable parameters
    provider = kwargs.get('provider', 'openai')
    model = kwargs.get('model', 'gpt-4o')  # More capable model for research
    streaming = kwargs.get('streaming', True)
    
    # MCP configuration
    config_file = kwargs.get('mcp_config_file', "research_server_config.json")
    mcp_servers = kwargs.get('mcp_servers', ["brave_search", "wikipedia"])
    
    logger.info(f"🔍 Creating research agent with sessions: {enable_sessions}")
    logger.info(f"🔍 Using model: {provider}/{model}")
    logger.info(f"🔍 MCP tools enabled: {enable_tools}")
    
    # Create MCP configuration if tools are enabled
    if enable_tools:
        try:
            _create_mcp_config(config_file)
        except Exception as e:
            logger.warning(f"Failed to create MCP config: {e}")
            enable_tools = False
    
    # Create agent with appropriate configuration
    try:
        if enable_tools:
            agent = ChukAgent(
                name="research_agent",
                provider=provider,
                model=model,
                description="Research assistant with web search and Wikipedia capabilities",
                instruction=_get_research_instruction(),
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
            logger.info("🔍 Research agent created successfully with MCP search tools")
            
        else:
            # Fallback without tools
            agent = ChukAgent(
                name="research_agent",
                provider=provider,
                model=model,
                description="Research assistant (search tools unavailable)",
                instruction=_get_fallback_instruction(),
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
            logger.warning("🔍 Created fallback research agent - MCP search tools unavailable")
            
    except Exception as e:
        logger.error(f"Failed to create research agent with MCP: {e}")
        logger.error("Creating basic research agent without tools")
        
        # Basic fallback
        agent = ChukAgent(
            name="research_agent",
            provider=provider,
            model=model,
            description="Basic research assistant",
            instruction="I'm a research assistant. I can help analyze information and provide insights based on my training, though I don't have access to real-time search tools.",
            streaming=streaming,
            enable_sessions=enable_sessions,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            session_ttl_hours=session_ttl_hours
        )
    
    # Debug logging
    logger.info(f"🔍 RESEARCH AGENT CREATED: {type(agent)}")
    logger.info(f"🔍 Internal sessions enabled: {agent.enable_sessions}")
    logger.info(f"🔍 Tools enabled: {getattr(agent, 'enable_tools', False)}")
    
    if enable_sessions:
        logger.info(f"🔍 Agent will manage research sessions internally")
    else:
        logger.info(f"🔍 External sessions will be managed by handler")
    
    return agent


def _create_mcp_config(config_file: str):
    """Create MCP configuration file for research tools."""
    config = {
        "mcpServers": {
            "brave_search": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {
                    "BRAVE_API_KEY": "${BRAVE_API_KEY}"
                },
                "description": "Web search via Brave Search API"
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
    
    # Warn about API key requirement
    if not os.getenv("BRAVE_API_KEY"):
        logger.warning("BRAVE_API_KEY environment variable not set - web search may not work")


def _get_research_instruction():
    """Get the full research instruction for agents with tools."""
    return """You are a Research Assistant specialized in finding and synthesizing information.

🔍 AVAILABLE TOOLS:
- Web search capabilities via Brave Search (for current information)
- Wikipedia lookup for encyclopedic and background information
- Fact-checking and verification across multiple sources

🎯 RESEARCH METHODOLOGY:
1. **Information Gathering**: Use your tools to gather relevant, current information
2. **Source Diversity**: Search multiple sources when possible for comprehensive coverage
3. **Cross-Reference**: Verify information between web search and Wikipedia
4. **Citation**: Always cite your sources when providing information
5. **Organization**: Structure complex answers with clear headings and logical flow

📝 RESPONSE GUIDELINES:
- Start with a **brief summary/answer** to the question
- Provide **detailed information** with proper source citations
- Use **bullet points or numbered lists** for clarity and readability
- Include **relevant links** when available and useful
- **Acknowledge limitations** or conflicting information when found
- **Suggest follow-up questions** for deeper research

🔍 SEARCH STRATEGY:
- Use **specific, targeted search terms** for better results
- Search for **recent information** when currency matters (news, trends, current events)
- Use **Wikipedia for background/foundational** information and context
- **Verify facts across multiple sources** when possible for accuracy
- **Combine general and specific** searches for comprehensive coverage

🎯 RESEARCH EXCELLENCE:
Always strive for accuracy, comprehensiveness, and clarity in your research. 
When you're uncertain about information, say so and suggest additional verification steps.
Focus on being helpful while maintaining intellectual honesty about the limits of available information."""


def _get_fallback_instruction():
    """Get instruction for agents without search tools."""
    return """I'm a Research Assistant, though my real-time search tools are currently unavailable.

🎯 HOW I CAN HELP:
- Analyze and synthesize information you provide
- Offer research methodologies and strategies
- Suggest search terms and research approaches
- Help organize and structure research findings
- Provide context and background from my training data

📝 LIMITATIONS:
- I cannot access current web search or Wikipedia in real-time
- My knowledge has a cutoff date and may not include recent events
- I cannot verify current facts or provide live data

💡 RESEARCH GUIDANCE:
I can help you plan research strategies, suggest sources to check, and analyze information you find. 
For current information, I recommend using external search tools or databases directly."""

