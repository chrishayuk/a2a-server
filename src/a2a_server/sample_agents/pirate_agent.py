# a2a_server/sample_agents/pirate_agent.py
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

# set the agent model
AGENT_MODEL = "openai/gpt-4o-mini"

# pirate agent
pirate_agent = Agent(
    name="pirate_agent",
    model=LiteLlm(model=AGENT_MODEL),
    description="Acts like a pirate",
    instruction="You are a pirate called Jolly Roger, you will act as a pirate including personality traits, and will respond in pirate speak"
)