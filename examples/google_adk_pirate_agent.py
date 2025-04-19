#!/usr/bin/env python3
# examples/google_adk_pirate_agent.py
"""
A2A Google ADK Agent Server Example

This example launches an A2A server using a GoogleADKHandler wrapped around
a pirate agent.
"""
import argparse
import logging
import uvicorn

# a2a
from a2a.server.app import create_app
from a2a.server.tasks.handlers.google_adk_handler import GoogleADKHandler
from a2a.server.tasks.handlers.adk_agent_adapter import ADKAgentAdapter
from a2a.server.logging import configure_logging

# import the sample agent
from a2a.server.sample_agents.pirate_agent import pirate_agent as agent

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="A2A Pirate Agent Server")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP server"
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Logging level"
    )
    args = parser.parse_args()
    
    # Configure logging
    configure_logging(
        level_name=args.log_level,
        quiet_modules={
            "httpx": "ERROR",
            "LiteLLM": "ERROR",
            "google.adk": "ERROR",
            "uvicorn": "WARNING",
        }
    )
    
    logger = logging.getLogger(__name__)
    
    # Create the handler
    adapter = ADKAgentAdapter(agent)
    handler_name = getattr(agent, 'name', 'pirate_agent')
    handler = GoogleADKHandler(adapter, name=handler_name)
    
    # Create the FastAPI app
    app = create_app(
        use_handler_discovery=False,
        custom_handlers=[handler],
        default_handler=handler
    )
    
    # Run the server
    logger.info(f"Starting A2A Pirate Agent Server on http://{args.host}:{args.port}")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower()
    )


if __name__ == "__main__":
    main()