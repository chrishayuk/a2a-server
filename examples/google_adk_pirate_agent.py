#!/usr/bin/env python3
# examples/google_adk_pirate_agent.py
"""
A2A Google ADK Agent Server Example

This example launches an A2A server using a GoogleADKHandler wrapped around
a pirate agent.
"""
import logging
import uvicorn

# a2a
from a2a.server.app import create_app
from a2a.server.tasks.handlers.google_adk_handler import GoogleADKHandler
from a2a.server.tasks.handlers.adk_agent_adapter import ADKAgentAdapter
from a2a.server.logging import configure_logging

# import the sample agent
from a2a.server.sample_agents.pirate_agent import pirate_agent as agent

# constants
HOST = "0.0.0.0"
PORT = 8000

def main():
    # Wrap the ADK Agent in the adapter
    adapter = ADKAgentAdapter(agent)

    # Instantiate handler
    handler = GoogleADKHandler(adapter)

    # Create the FastAPI app with only this custom handler
    app = create_app(
        use_handler_discovery=False,
        custom_handlers=[handler],
        default_handler=handler
    )

    # Start the server
    uvicorn.run(
        app,
        host=HOST,
        port=PORT
    )

if __name__ == "__main__":
    main()
