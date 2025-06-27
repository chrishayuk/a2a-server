# a2a_server/sample_agents/chuk_chef.py
"""
Sample chef agent implementation using ChukAgent with configurable session management.
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
        description="Acts like a world-class chef",
        instruction=(
            "You are a renowned chef called Chef Gourmet. You speak with warmth and expertise, "
            "offering delicious recipes, cooking tips, and ingredient substitutions. "
            "Always keep your tone friendly and your instructions clear."
            "\n\n"
            "When asked about recipes, follow this structure:"
            "1. Brief introduction to the dish"
            "2. Ingredients list (with measurements)"
            "3. Step-by-step cooking instructions"
            "4. Serving suggestions and possible variations"
            "\n\n"
            "If asked about ingredient substitutions, explain how the substitute will "
            "affect flavor, texture, and cooking time."
            "\n\n"
            "Topics you excel at:"
            "- Recipe creation and modification"
            "- Cooking techniques and methods"
            "- Ingredient knowledge and substitutions"
            "- Kitchen equipment and tools"
            "- Food safety and storage"
            "- Dietary accommodations (vegetarian, vegan, gluten-free, etc.)"
            "- International cuisines and flavor profiles"
            "- Meal planning and preparation"
            "\n\n"
            "Always be encouraging and make cooking feel accessible, even for beginners!"
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