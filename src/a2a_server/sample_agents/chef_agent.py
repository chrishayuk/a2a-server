# a2a_server/sample_agents/chef_agent.py
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

# use the same underlying model
AGENT_MODEL = "openai/gpt-4o-mini"

chef_agent = Agent(
    name="chef_agent",
    model=LiteLlm(model=AGENT_MODEL),
    description="Acts like a world-class chef",
    instruction=(
        "You are a renowned chef called Chef Gourmet. You speak with warmth and expertise, "
        "offering delicious recipes, cooking tips, and ingredient substitutions. "
        "Always keep your tone friendly and your instructions clear."
    )
)
