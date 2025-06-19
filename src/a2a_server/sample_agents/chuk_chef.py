# a2a_server/sample_agents/chuk_chef.py
"""
Sample chef agent implementation using ChukAgent with external session management.
"""
import logging
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

logger = logging.getLogger(__name__)

# Create a pure agent instance - this is all you need!
chef_agent = ChukAgent(
    name="chef_agent",
    provider="openai",
    model="gpt-4o-mini",
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
    ),
    streaming=True,
    # CRITICAL: Disable internal session management - let ResilientHandler manage sessions
    enable_sessions=False,  # ← This is the key change
    enable_tools=False,     # Keep tools disabled to avoid MCP complexity
    debug_tools=False       # Reduce log noise
)

# Debug the chef_agent
logger.info(f"🍳 CHEF AGENT CREATED: {type(chef_agent)}")
logger.info(f"🍳 Internal sessions enabled: {chef_agent.enable_sessions}")
logger.info(f"🍳 External sessions will be managed by ResilientHandler")