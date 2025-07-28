#!/usr/bin/env python3
# a2a_server/routes/handlers.py
"""
Per-handler route registration for the A2A server.

This module registers routes for each handler discovered by the task manager,
providing handler-specific endpoints for health checks, agent cards, transport,
and streaming responses.

Updated to properly support A2A CLI agent discovery using /.well-known/agent.json
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request, Query, HTTPException, Response, WebSocket

# a2a imports
from a2a_server.agent_card import get_agent_cards, create_handler_specific_agent_card
from a2a_server.transport.sse import _create_sse_response

# logger
logger = logging.getLogger(__name__)


def register_handler_routes(
    app: FastAPI,
    task_manager,
    handlers_config: dict
):
    """
    Register comprehensive per-handler routes for each handler in the task manager.
    
    For each handler, this registers:
    - GET /{handler_name} - Handler root endpoint with optional SSE streaming
    - GET /{handler_name}/.well-known/agent.json - Agent card endpoint (CLI discovery)
    - POST /{handler_name}/rpc - Handler RPC endpoint
    - WebSocket /{handler_name}/ws - Handler WebSocket endpoint
    - GET /{handler_name}/events - Handler SSE events endpoint
    - GET /{handler_name}/health - Handler health check
    
    Args:
        app: FastAPI application instance
        task_manager: Task manager containing handlers
        handlers_config: Configuration dict for handlers
    """
    
    # Get protocol and event bus from app state
    protocol = getattr(app.state, 'protocol', None)
    event_bus = getattr(app.state, 'event_bus', None)
    
    # Register routes for each handler
    registered_handlers = task_manager.get_handlers()
    logger.info(f"Registering comprehensive routes for {len(registered_handlers)} handlers")
    
    for handler_name, handler_instance in registered_handlers.items():
        logger.debug(f"Setting up routes for handler: {handler_name}")
        
        # Get handler configuration
        handler_config = handlers_config.get(handler_name, {})
        
        # ── Handler root endpoint ──────────────────────────────────────
        async def _handler_root(
            request: Request,
            _h=handler_name,  # Capture handler name in closure
            _config=handler_config,  # Capture config in closure
            task_ids: Optional[List[str]] = Query(None)
        ):
            """Handler root endpoint with optional SSE streaming."""
            if task_ids:
                logger.debug("Upgrading GET /%s to SSE streaming: %r", _h, task_ids)
                return await _create_sse_response(app.state.event_bus, task_ids)

            base_url = str(request.base_url).rstrip("/")
            handler_url = f"{base_url}/{_h}"
            
            return {
                "handler": _h,
                "url": handler_url,
                "type": _config.get("type"),
                "status": "active",
                "endpoints": {
                    "rpc": f"{handler_url}/rpc",
                    "events": f"{handler_url}/events", 
                    "ws": f"{handler_url}/ws",
                    "agent_card": f"{handler_url}/.well-known/agent.json",
                    "health": f"{handler_url}/health"
                },
                "capabilities": _config.get("agent_card", {}).get("capabilities", {}),
                "version": _config.get("agent_card", {}).get("version", "1.0.0")
            }

        app.add_api_route(
            f"/{handler_name}",
            _handler_root,
            methods=["GET"],
            include_in_schema=False,
            tags=[handler_name]
        )

        # ── Well-known agent card endpoint (CLI discovery) ─────────────
        async def _handler_agent_card(
            request: Request, 
            _h=handler_name,  # Capture handler name in closure
            _config=handler_config  # Capture config in closure
        ):
            """Handler-specific agent card endpoint for CLI discovery."""
            base_url = str(request.base_url).rstrip("/")
            
            try:
                card = create_handler_specific_agent_card(
                    _h, 
                    base_url, 
                    _config,
                    str(request.url)
                )
                card_dict = card.model_dump(exclude_none=True)
                logger.info(f"Serving /.well-known/agent.json for {_h}: {card_dict.get('url')}")
                return card_dict
                
            except Exception as e:
                logger.error(f"Failed to create agent card for {_h}: {e}")
                
                # Enhanced fallback agent card with proper structure
                # ✅ CRITICAL: Ensure we use the same base_url from the request
                # This prevents localhost fallback issues
                parsed_url = str(request.url)
                if "fly.dev" in parsed_url:
                    # Force the correct base URL for production
                    base_url = "https://a2a-server.fly.dev"
                elif "localhost" not in base_url and "127.0.0.1" not in base_url:
                    # Keep the provided base_url if it's not localhost
                    pass
                else:
                    # Local development - keep as is
                    pass
                    
                handler_url = f"{base_url}/{_h}"
                agent_card_config = _config.get("agent_card", {})
                
                logger.warning(f"🔧 Creating fallback agent card for {_h} - base_url: {base_url}, request_url: {request.url}")
                
                fallback_card = {
                    "name": agent_card_config.get("name", _h.replace("_", " ").title()),
                    "description": agent_card_config.get("description", f"A2A handler for {_h}"),
                    "url": handler_url,
                    "version": agent_card_config.get("version", "1.0.0"),
                    "capabilities": {
                        "streaming": agent_card_config.get("capabilities", {}).get("streaming", True),
                        "tools": _config.get("enable_tools", False),
                        "sessions": _config.get("enable_sessions", False),
                        "pushNotifications": False
                    },
                    "defaultInputModes": agent_card_config.get("defaultInputModes", ["text/plain"]),
                    "defaultOutputModes": agent_card_config.get("defaultOutputModes", ["text/plain"]),
                    "skills": agent_card_config.get("skills", [{
                        "id": f"{_h}-default",
                        "name": _h.replace("_", " ").title(),
                        "description": f"Default capability for {_h}",
                        "tags": [_h, "a2a", "agent"],
                    }])
                }
                
                # Add optional fields if configured
                if agent_card_config.get("documentationUrl"):
                    fallback_card["documentationUrl"] = agent_card_config["documentationUrl"]
                elif agent_card_config.get("documentation_url"):
                    fallback_card["documentationUrl"] = agent_card_config["documentation_url"]
                else:
                    fallback_card["documentationUrl"] = f"{handler_url}/docs"
                
                if agent_card_config.get("provider"):
                    fallback_card["provider"] = agent_card_config["provider"]
                
                if agent_card_config.get("authentication"):
                    fallback_card["authentication"] = agent_card_config["authentication"]
                
                logger.info(f"Using fallback agent card for {_h}")
                return fallback_card

        app.add_api_route(
            f"/{handler_name}/.well-known/agent.json",
            _handler_agent_card,
            methods=["GET"],
            include_in_schema=False,
            tags=[handler_name]
        )

        # ── Handler RPC endpoint ───────────────────────────────────────
        if protocol:
            async def _handler_rpc(
                request: Request,
                _h=handler_name
            ):
                """Handler-specific RPC endpoint."""
                try:
                    body = await request.body()
                    content_type = request.headers.get("content-type", "")
                    
                    if not body:
                        raise HTTPException(status_code=400, detail="Empty request body")
                    
                    if "application/json" not in content_type:
                        raise HTTPException(status_code=400, detail="Content-Type must be application/json")
                    
                    # Process the RPC request
                    response_data = await protocol.handle_request(body.decode('utf-8'))
                    
                    return Response(
                        content=response_data,
                        media_type="application/json",
                        headers={
                            "Content-Length": str(len(response_data.encode('utf-8'))),
                            "Connection": "close"
                        }
                    )
                    
                except Exception as e:
                    logger.error(f"Handler {_h} RPC error: {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            app.add_api_route(
                f"/{handler_name}/rpc",
                _handler_rpc,
                methods=["POST"],
                include_in_schema=False,
                tags=[handler_name]
            )

        # ── Handler WebSocket endpoint ─────────────────────────────────
        if protocol:
            async def _handler_websocket(
                websocket: WebSocket,
                _h=handler_name
            ):
                """Handler-specific WebSocket endpoint."""
                await websocket.accept()
                
                try:
                    while True:
                        message = await websocket.receive_text()
                        response = await protocol.handle_request(message)
                        await websocket.send_text(response)
                        
                except Exception as e:
                    logger.error(f"Handler {_h} WebSocket error: {e}")
                    await websocket.close()

            app.add_api_route(
                f"/{handler_name}/ws",
                _handler_websocket,
                methods=["GET"],
                include_in_schema=False,
                tags=[handler_name]
            )

        # ── Handler SSE events endpoint ────────────────────────────────
        if event_bus:
            async def _handler_events(
                request: Request,
                _h=handler_name,
                task_ids: Optional[List[str]] = Query(None)
            ):
                """Handler-specific SSE events endpoint."""
                return await _create_sse_response(app.state.event_bus, task_ids)

            app.add_api_route(
                f"/{handler_name}/events",
                _handler_events,
                methods=["GET"],
                include_in_schema=False,
                tags=[handler_name]
            )

        # ── Handler health endpoint ────────────────────────────────────
        async def _handler_health(
            _h=handler_name,
            _config=handler_config,
            _instance=handler_instance
        ):
            """Handler-specific health check."""
            health_info = {
                "handler": _h,
                "status": "healthy",
                "type": _config.get("type"),
                "class": _instance.__class__.__name__,
                "module": _instance.__class__.__module__
            }
            
            # Add handler-specific health info if available
            if hasattr(_instance, 'get_health_status'):
                try:
                    handler_health = _instance.get_health_status()
                    health_info.update(handler_health)
                except Exception as e:
                    health_info["health_check_error"] = str(e)
            
            # Add configuration status
            health_info["configuration"] = {
                "sessions_enabled": _config.get("enable_sessions", False),
                "tools_enabled": _config.get("enable_tools", False),
                "streaming_enabled": _config.get("streaming", True)
            }
            
            return health_info

        app.add_api_route(
            f"/{handler_name}/health",
            _handler_health,
            methods=["GET"],
            include_in_schema=False,
            tags=[handler_name]
        )

        # ── CLI Compatibility endpoint (agent-card.json) ───────────────
        # The CLI has a bug where it looks for /agent-card.json instead of /.well-known/agent.json
        async def _handler_agent_card_compat(
            request: Request, 
            _h=handler_name,  # Capture handler name in closure
            _config=handler_config  # Capture config in closure
        ):
            """CLI compatibility endpoint - same as well-known endpoint."""
            return await _handler_agent_card(request, _h, _config)

        app.add_api_route(
            f"/{handler_name}/agent-card.json",
            _handler_agent_card_compat,
            methods=["GET"],
            include_in_schema=False,
            tags=[handler_name]
        )

        logger.debug(f"✅ Registered all routes for handler: {handler_name}")

    logger.info(f"✅ Handler route registration complete for {len(registered_handlers)} handlers")


def get_handler_endpoints(handler_name: str, base_url: str) -> Dict[str, str]:
    """
    Get all endpoints for a specific handler.
    
    Args:
        handler_name: Name of the handler
        base_url: Base URL of the server
        
    Returns:
        Dictionary mapping endpoint names to URLs
    """
    handler_url = f"{base_url.rstrip('/')}/{handler_name}"
    
    return {
        "root": handler_url,
        "agent_card": f"{handler_url}/.well-known/agent.json",
        "rpc": f"{handler_url}/rpc",
        "events": f"{handler_url}/events",
        "ws": f"{handler_url}/ws",
        "health": f"{handler_url}/health"
    }


def validate_handler_routes(app: FastAPI, handler_names: List[str]) -> Dict[str, Any]:
    """
    Validate that all expected routes are registered for handlers.
    
    Args:
        app: FastAPI application instance
        handler_names: List of handler names to validate
        
    Returns:
        Validation results dictionary
    """
    validation_results = {
        "total_handlers": len(handler_names),
        "validated_handlers": {},
        "missing_routes": [],
        "extra_routes": []
    }
    
    expected_routes = [
        "",  # root
        "/.well-known/agent.json",
        "/rpc", 
        "/ws",
        "/events",
        "/health"
    ]
    
    # Get all registered routes
    registered_paths = {route.path for route in app.routes}
    
    for handler_name in handler_names:
        handler_routes = {}
        missing_routes = []
        
        for route_suffix in expected_routes:
            expected_path = f"/{handler_name}{route_suffix}"
            if expected_path in registered_paths:
                handler_routes[route_suffix or "root"] = "registered"
            else:
                missing_routes.append(expected_path)
        
        validation_results["validated_handlers"][handler_name] = {
            "routes": handler_routes,
            "missing": missing_routes,
            "complete": len(missing_routes) == 0
        }
        
        if missing_routes:
            validation_results["missing_routes"].extend(missing_routes)
    
    return validation_results