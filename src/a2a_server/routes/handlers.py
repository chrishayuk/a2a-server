#!/usr/bin/env python3
# File: a2a_server/routes/handlers.py (Updated)

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
    # per-handler GET health and streaming
    for handler_name in task_manager.get_handlers().keys():
        async def _handler_health(
            request: Request,
            _h=handler_name,
            task_ids: Optional[List[str]] = Query(None)
        ):
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

        app.add_api_route(
            f"/{handler_name}",
            _handler_health,
            methods=["GET"],
            include_in_schema=False,
        )

        async def _handler_card(request: Request, _h=handler_name):
            base = str(request.base_url).rstrip("/")
            if not hasattr(app.state, "agent_cards"):
                app.state.agent_cards = get_agent_cards(handlers_config, base)
            card = app.state.agent_cards.get(_h)
            if card:
                # Updated: Use model_dump() instead of dict()
                return card.model_dump(exclude_none=True)

            # fallback minimal agent-card, now with "mount"
            return {
                "name": _h.replace("_", " ").title(),
                "description": f"A2A handler for {_h}",
                # tell the client to mount under /<handler_name>
                "mount": _h,
                # base URL for this handler
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

        app.add_api_route(
            f"/{handler_name}/.well-known/agent.json",
            _handler_card,
            methods=["GET"],
            include_in_schema=False,
        )