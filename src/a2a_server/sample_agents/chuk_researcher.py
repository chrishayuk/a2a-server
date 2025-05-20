# a2a_server/sample_agents/chuk_researcher.py
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent

# Define search tools
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web for current information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    }
}

LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_wikipedia",
        "description": "Look up a topic on Wikipedia",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic to look up"
                }
            },
            "required": ["topic"]
        }
    }
}

# Mock tool implementations
async def search_web(query: str):
    """Mock web search implementation."""
    import asyncio
    await asyncio.sleep(0.5)  # Simulate API call
    
    # This would be replaced with actual search API call
    return {
        "query": query,
        "results": [
            {
                "title": f"Result for {query}",
                "snippet": f"This is a simulated search result for the query: {query}",
                "url": f"https://example.com/search?q={query}"
            },
            {
                "title": f"Another result for {query}",
                "snippet": f"More information about: {query}",
                "url": f"https://example.org/info?topic={query}"
            }
        ]
    }

async def lookup_wikipedia(topic: str):
    """Mock Wikipedia lookup implementation."""
    import asyncio
    await asyncio.sleep(0.5)  # Simulate API call
    
    # This would be replaced with actual Wikipedia API call
    return {
        "topic": topic,
        "summary": f"This is a simulated Wikipedia summary for: {topic}",
        "url": f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}"
    }

# Define a research agent with tool capabilities
research_agent = ChukAgent(
    name="research_agent",
    provider="openai",
    model="gpt-4o",  # Using a more capable model for research
    description="Research assistant with web search capabilities",
    instruction=(
        "You are a Research Assistant specialized in finding and synthesizing information. "
        "When asked questions, use your tools to gather relevant information before answering. "
        "Always cite your sources when providing information. "
        "Your goal is to provide comprehensive, accurate, and well-organized answers, while "
        "acknowledging any limitations in the available information."
        "\n\n"
        "Follow these guidelines:"
        "1. When uncertain about facts, use search tools"
        "2. Synthesize information from multiple sources when possible"
        "3. Structure complex answers with clear headings"
        "4. Always provide sources for factual information"
        "5. Acknowledge when information might be incomplete"
    ),
    tools=[SEARCH_TOOL, LOOKUP_TOOL],
    tool_handlers={
        "search_web": search_web,
        "lookup_wikipedia": lookup_wikipedia
    }
)