#!/usr/bin/env python3
# examples/google_adk_pirate_agent.py
"""
A2A Google ADK Agent Server Example

This example launches an A2A server using a GoogleADKHandler wrapped around
any Google ADK `Agent` via the `ADKAgentAdapter` shim.
"""
import logging
import uvicorn

# a2a
from a2a.server.app import create_app
from a2a.server.tasks.handlers.google_adk_handler import GoogleADKHandler
from a2a.server.tasks.handlers.adk_agent_adapter import ADKAgentAdapter

# agents
from pirate_agent import pirate_agent as agent


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Wrap the native ADK agent with our adapter shim
    adapter = ADKAgentAdapter(agent)

    # Name the handler after the agent's internal name
    handler_name = getattr(agent, 'name', 'adk_agent')
    handler = GoogleADKHandler(adapter, name=handler_name)

    # Create the FastAPI app, registering only this custom handler
    app = create_app(
        use_handler_discovery=False,
        custom_handlers=[handler],
        default_handler=handler,
    )

    # Launch via Uvicorn
    logger.info(f"Starting A2A ADK Agent Server on http://127.0.0.1:8000 (handler: {handler_name})...")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
