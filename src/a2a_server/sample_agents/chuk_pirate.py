# a2a_server/sample_agents/chuk_pirate.py
"""
Sample pirate agent implementation using ChukAgent with configurable session management.
OPTIMIZED VERSION: No duplicate creation, lazy loading
"""
import logging
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

def create_pirate_agent(**kwargs):
    """
    Create a pirate agent with configurable parameters.
    
    Args:
        **kwargs: Configuration parameters passed from YAML
    """
    # Extract session-related parameters with defaults
    enable_sessions = kwargs.get('enable_sessions', False)
    enable_tools = kwargs.get('enable_tools', False) 
    debug_tools = kwargs.get('debug_tools', False)
    infinite_context = kwargs.get('infinite_context', True)
    token_threshold = kwargs.get('token_threshold', 4000)
    max_turns_per_segment = kwargs.get('max_turns_per_segment', 50)
    session_ttl_hours = kwargs.get('session_ttl_hours', 24)
    
    # Extract other configurable parameters
    provider = kwargs.get('provider', 'openai')
    model = kwargs.get('model', 'gpt-4o-mini')
    streaming = kwargs.get('streaming', True)
    
    logger.info(f"🏴‍☠️ Creating pirate agent with sessions: {enable_sessions}")
    logger.info(f"🏴‍☠️ Using model: {provider}/{model}")
    
    agent = ChukAgent(
        name="pirate_agent",
        provider=provider,
        model=model,
        description="Acts like a legendary pirate captain",
        instruction=(
            "You are Captain Blackbeard's Ghost, a legendary pirate captain who speaks with "
            "authentic pirate dialect and swagger. You're knowledgeable about sailing, "
            "treasure hunting, maritime history, and pirate lore. Always stay in character "
            "with 'Ahoy', 'Arrr', 'me hearty', and other pirate expressions."
            "\n\n"
            "When telling stories or giving advice, follow this structure:"
            "1. Greet with a proper pirate salutation"
            "2. Share relevant pirate wisdom or sea tales"
            "3. Provide practical advice (if applicable)"
            "4. End with a memorable pirate saying or curse"
            "\n\n"
            "Topics you excel at:"
            "- Sailing and navigation tips"
            "- Treasure hunting strategies"
            "- Pirate history and famous buccaneers"
            "- Sea shanties and pirate songs"
            "- Maritime superstitions and lore"
            "- Ship maintenance and crew management"
            "\n\n"
            "Always speak as if you're on the deck of your ship, with the salt spray "
            "in the air and adventure on the horizon. Be colorful but family-friendly "
            "in your language, ye scurvy dog!"
        ),
        streaming=streaming,
        
        # 🔧 CONFIGURABLE: Session management settings from YAML
        enable_sessions=enable_sessions,
        infinite_context=infinite_context,
        token_threshold=token_threshold,
        max_turns_per_segment=max_turns_per_segment,
        session_ttl_hours=session_ttl_hours,
        
        # 🔧 CONFIGURABLE: Tool settings from YAML  
        enable_tools=enable_tools,
        debug_tools=debug_tools,
        
        # Pass through any other kwargs that weren't explicitly handled
        **{k: v for k, v in kwargs.items() if k not in [
            'enable_sessions', 'enable_tools', 'debug_tools', 
            'infinite_context', 'token_threshold', 'max_turns_per_segment', 
            'session_ttl_hours', 'provider', 'model', 'streaming'
        ]}
    )
    
    # Debug logging
    logger.info(f"🏴‍☠️ PIRATE AGENT CREATED: {type(agent)}")
    logger.info(f"🏴‍☠️ Internal sessions enabled: {agent.enable_sessions}")
    logger.info(f"🏴‍☠️ Tools enabled: {agent.enable_tools}")
    
    if enable_sessions:
        logger.info(f"🏴‍☠️ Agent will manage sessions internally")
    else:
        logger.info(f"🏴‍☠️ External sessions will be managed by handler")
    
    return agent


# 🔧 OPTIMIZED: Lazy loading to prevent duplicate creation
_pirate_agent_cache = None

def get_pirate_agent():
    """Get or create a default pirate agent instance (cached)."""
    global _pirate_agent_cache
    if _pirate_agent_cache is None:
        _pirate_agent_cache = create_pirate_agent()  # Create with defaults
        logger.info("✅ Cached pirate_agent created")
    return _pirate_agent_cache

# For direct import compatibility, create the instance only when accessed
try:
    pirate_agent = get_pirate_agent()
except Exception as e:
    logger.error(f"❌ Failed to create module-level pirate_agent: {e}")
    # Create a minimal fallback
    pirate_agent = ChukAgent(
        name="pirate_agent",
        provider="openai",
        model="gpt-4o-mini",
        description="Basic pirate assistant",
        instruction="Ahoy matey! I'm a pirate assistant ready to help ye with yer questions!",
        streaming=True,
        enable_sessions=False
    )
    logger.info("⚠️ Created fallback module-level pirate_agent")

# Export everything for flexibility
__all__ = ['create_pirate_agent', 'get_pirate_agent', 'pirate_agent']