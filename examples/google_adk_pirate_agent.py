#!/usr/bin/env python3
# examples/google_adk_pirate_agent.py
"""
A2A Google ADK Agent Server Example

This example launches an A2A server by passing a raw Google ADK `Agent`
directly into the handler; no manual adapter import or `use_handler_discovery`
flag is needed.
"""
import uvicorn

# a2a imports
from a2a_server.app import create_app
from a2a_server.tasks.handlers.google_adk_handler import GoogleADKHandler

# import the sample agent
from a2a_server.sample_agents.pirate_agent import pirate_agent as agent

# constants
HOST = "0.0.0.0"
PORT = 8000

def main():
    # Instantiate the handler directly with the raw ADK agent
    handler = GoogleADKHandler(agent)

    # Create the FastAPI app with just this handler
    app = create_app(
        handlers=[handler]
    )

    # Launch the server
    uvicorn.run(app, host=HOST, port=PORT)

if __name__ == "__main__":
    main()