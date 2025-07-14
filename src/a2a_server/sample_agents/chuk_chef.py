# a2a_server/sample_agents/chuk_chef.py
"""
Sample chef agent implementation using ChukAgent with configurable session management.
OPTIMIZED VERSION: No duplicate creation, lazy loading
"""
import logging
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

def create_chef_agent(**kwargs):
    """
    Create a chef agent with configurable parameters.
    
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
    
    logger.info(f"🍳 Creating chef agent with sessions: {enable_sessions}")
    logger.info(f"🍳 Using model: {provider}/{model}")
    
    agent = ChukAgent(
        name="chef_agent",
        provider=provider,
        model=model,
        description="Professional chef with culinary expertise",
        instruction=(
            "You are Chef Gourmet, a world-renowned professional chef with expertise in "
            "international cuisine, baking, and culinary techniques. You provide detailed, "
            "practical cooking advice with precise measurements and clear instructions."
            "\n\n"
            "When creating recipes, follow this structure:"
            "1. Brief description of the dish"
            "2. Prep time and cooking time"
            "3. Ingredients list with exact measurements"
            "4. Step-by-step instructions"
            "5. Cooking tips and variations"
            "6. Serving suggestions"
            "\n\n"
            "Specialties:"
            "- Classic French techniques"
            "- Italian pasta and risotto"
            "- Pastry and baking"
            "- Seasonal cooking"
            "- Dietary adaptations (vegetarian, gluten-free, etc.)"
            "- Ingredient substitutions"
            "- Kitchen equipment recommendations"
            "\n\n"
            "Always provide practical, achievable recipes with clear explanations of "
            "techniques. Include helpful tips for home cooks and explain why certain "
            "steps are important. Be encouraging and share your passion for great food!"
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
    logger.info(f"🍳 CHEF AGENT CREATED: {type(agent)}")
    logger.info(f"🍳 Internal sessions enabled: {agent.enable_sessions}")
    logger.info(f"🍳 Tools enabled: {agent.enable_tools}")
    
    if enable_sessions:
        logger.info(f"🍳 Agent will manage sessions internally")
    else:
        logger.info(f"🍳 External sessions will be managed by handler")
    
    return agent


# 🔧 OPTIMIZED: Lazy loading to prevent duplicate creation
_chef_agent_cache = None

def get_chef_agent():
    """Get or create a default chef agent instance (cached)."""
    global _chef_agent_cache
    if _chef_agent_cache is None:
        _chef_agent_cache = create_chef_agent()  # Create with defaults
        logger.info("✅ Cached chef_agent created")
    return _chef_agent_cache

# For direct import compatibility, create the instance only when accessed
try:
    chef_agent = get_chef_agent()
except Exception as e:
    logger.error(f"❌ Failed to create module-level chef_agent: {e}")
    # Create a minimal fallback
    chef_agent = ChukAgent(
        name="chef_agent",
        provider="openai",
        model="gpt-4o-mini",
        description="Basic chef assistant",
        instruction="I'm a cooking assistant. I can help with recipes and cooking advice.",
        streaming=True,
        enable_sessions=False
    )
    logger.info("⚠️ Created fallback module-level chef_agent")

# Export everything for flexibility
__all__ = ['create_chef_agent', 'get_chef_agent', 'chef_agent']