#!/usr/bin/env python3
# a2a_server/routes/handlers.py
"""
Per-handler route registration for the A2A server.

This module registers routes for each handler discovered by the task manager,
providing handler-specific endpoints for health checks, agent cards, and
streaming responses.
"""

import logging
from typing import List, Optional
from fastapi import FastAPI, Request, Query

# a2a imports
from a2a_server.agent_card import get_agent_cards
from a2a_server.transport.sse import _create_sse_response

# logger
logger = logging.getLogger(__name__)


def register_handler_routes(
    app: FastAPI,
    task_manager,
    handlers_config: dict
):
    """
    Register per-handler routes for each handler in the task manager.
    
    For each handler, this registers:
    - GET /{handler_name} - Health endpoint with optional SSE streaming
    - GET /{handler_name}/.well-known/agent.json - Agent card endpoint
    
    Args:
        app: FastAPI application instance
        task_manager: Task manager containing handlers
        handlers_config: Configuration dict for handlers
    """
    # per-handler GET health and streaming
    for handler_name in task_manager.get_handlers().keys():
        
        # Create handler health endpoint
        async def _handler_health(
            request: Request,
            _h=handler_name,  # Capture handler name in closure
            task_ids: Optional[List[str]] = Query(None)
        ):
            """Handler health endpoint with optional SSE streaming."""
            if task_ids:
                logger.debug(
                    "Upgrading GET /%s to SSE streaming: %r", _h, task_ids
                )
                return await _create_sse_response(app.state.event_bus, task_ids)

            base = str(request.base_url).rstrip("/")
            return {
                "handler": _h,
                "endpoints": {
                    "rpc":    f"/{_h}/rpc",
                    "events": f"/{_h}/events",
                    "ws":     f"/{_h}/ws",
                },
                "handler_agent_card": f"{base}/{_h}/.well-known/agent.json",
            }

        # Register the health endpoint
        app.add_api_route(
            f"/{handler_name}",
            _handler_health,
            methods=["GET"],
            include_in_schema=False,
        )

        # Create handler agent card endpoint
        async def _handler_card(
            request: Request, 
            _h=handler_name  # Capture handler name in closure
        ):
            """Handler-specific agent card endpoint."""
            base = str(request.base_url).rstrip("/")
            
            # Get or create agent cards cache
            if not hasattr(app.state, "agent_cards"):
                app.state.agent_cards = get_agent_cards(handlers_config, base)
            
            card = app.state.agent_cards.get(_h)
            if card:
                # Use model_dump() for Pydantic v2 compatibility
                return card.model_dump(exclude_none=True)

            # Fallback minimal agent-card
            return {
                "name": _h.replace("_", " ").title(),
                "description": f"A2A handler for {_h}",
                "url": f"{base}/{_h}",
                "version": "1.0.0",
                "capabilities": {"streaming": True},
                "defaultInputModes": ["text/plain"],
                "defaultOutputModes": ["text/plain"],
                "skills": [{
                    "id": f"{_h}-default",
                    "name": _h.replace("_", " ").title(),
                    "description": f"Default capability for {_h}",
                    "tags": [_h],
                }],
            }

        # Register the agent card endpoint
        app.add_api_route(
            f"/{handler_name}/.well-known/agent.json",
            _handler_card,
            methods=["GET"],
            include_in_schema=False,
        )

    logger.debug(f"Registered routes for {len(task_manager.get_handlers())} handlers")