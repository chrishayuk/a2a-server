# File: a2a/server/app.py
"""
A2A server application factory with support for agent cards.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging
from typing import Optional, List, Dict, Any

from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.tasks.task_manager import TaskManager
from a2a.server.pubsub import EventBus
from a2a.server.methods import register_methods
from a2a.server.transport import setup_http, setup_ws, setup_sse
from a2a.server.tasks.discovery import register_discovered_handlers
from a2a.server.tasks.handlers.echo_handler import EchoHandler
from a2a.server.tasks.task_handler import TaskHandler
from a2a.server.agent_card import get_agent_cards, AgentCard

logger = logging.getLogger(__name__)

def create_app(
    handlers: Optional[List[TaskHandler]] = None,
    *,
    use_discovery: bool = False,
    handler_packages: Optional[List[str]] = None,
    handlers_config: Optional[Dict[str, Dict[str, Any]]] = None
) -> FastAPI:
    """
    Build the FastAPI app with direct handler routing and agent card support.
    
    Args:
        handlers: Optional list of handlers to register (first is default)
        use_discovery: Whether to auto-discover handlers
        handler_packages: Optional packages to search for handlers
        handlers_config: Configuration for handlers from YAML
        
    Returns:
        FastAPI application
    """
    # Create core components
    event_bus = EventBus()
    task_manager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()

    # Register handlers
    if handlers:
        # Register provided handlers (first is default)
        default = handlers[0]
        for h in handlers:
            is_def = (h is default)
            task_manager.register_handler(h, default=is_def)
            logger.debug(f"Registered handler: {h.name}{' (default)' if is_def else ''}")
        logger.info(f"Registered {len(handlers)} handler(s), default='{default.name}'")
    elif use_discovery:
        # Use automatic discovery
        logger.info("Discovering handlers automatically")
        register_discovered_handlers(task_manager, packages=handler_packages)
    else:
        # Fallback to EchoHandler
        logger.info("No handlers → using EchoHandler fallback")
        task_manager.register_handler(EchoHandler(), default=True)

    # JSON‑RPC wiring
    register_methods(protocol, task_manager)
    logger.debug("JSON-RPC methods registered")

    # Create FastAPI app
    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent JSON‑RPC over HTTP, WS, SSE",
    )
    
    # Store handlers_config in app state for access in routes
    app.state.handlers_config = handlers_config or {}
    
    # Create agent cards for each handler
    agent_cards = {}
    
    # Register transports with explicit endpoint registration for each handler
    setup_http(app, protocol, task_manager)
    setup_ws(app, protocol, event_bus, task_manager)
    setup_sse(app, event_bus, task_manager)
    logger.debug("Transports configured with direct handler mounting")
    
    # Add a root health check endpoint
    @app.get("/", include_in_schema=False)
    async def health_check(request: Request):
        """Root health check endpoint."""
        default_handler = task_manager.get_default_handler()
        handlers = task_manager.get_handlers()
        
        # Generate base URL
        base_url = str(request.base_url).rstrip('/')
        
        return {
            "status": "ok",
            "default_handler": default_handler,
            "handlers": handlers,
            "api": {
                "rpc": "/rpc",  # Default handler at root
                "events": "/events",  # Default handler at root
                "ws": "/ws",  # Default handler at root
                "{handler}/rpc": "Specific handler RPC endpoint",
                "{handler}/events": "Specific handler events endpoint",
                "{handler}/ws": "Specific handler WebSocket endpoint"
            },
            "agent_card": f"{base_url}/.well-known/agent.json"
        }
    
    # A2A Protocol-compliant agent card endpoint for the default handler
    @app.get("/.well-known/agent.json", include_in_schema=False)
    async def default_agent_card(request: Request):
        """Return the agent card for the default handler."""
        default_handler = task_manager.get_default_handler()
        if not default_handler:
            return JSONResponse(status_code=404, content={"error": "No default handler found"})
        
        # Generate base URL
        base_url = str(request.base_url).rstrip('/')
        
        # Generate agent cards if not already done
        if not hasattr(app.state, "agent_cards"):
            app.state.agent_cards = get_agent_cards(
                app.state.handlers_config, 
                base_url
            )
        
        # Return the agent card for the default handler
        if default_handler in app.state.agent_cards:
            return app.state.agent_cards[default_handler].dict(exclude_none=True)
        
        # If no card found, create a minimal one
        handler_config = app.state.handlers_config.get(default_handler, {})
        default_card = {
            "name": handler_config.get("name", default_handler.replace("_", " ").title()),
            "description": f"A2A handler for {default_handler}",
            "url": f"{base_url}",
            "version": "1.0.0",
            "capabilities": {
                "streaming": True,
                "pushNotifications": False
            },
            "authentication": {
                "schemes": ["None"]
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [{
                "id": f"{default_handler}-default",
                "name": default_handler.replace("_", " ").title(),
                "description": f"Default capability for {default_handler}",
                "tags": [default_handler]
            }]
        }
        return default_card
    
    # Add handler-specific endpoints
    for handler_name in task_manager.get_handlers():
        # Health check endpoint using function factory to properly capture handler_name
        def create_health_endpoint(name):
            @app.get(f"/{name}", include_in_schema=False)
            async def handler_health(request: Request):
                """Handler-specific health check."""
                base_url = str(request.base_url).rstrip('/')
                return {
                    "handler": name,
                    "endpoints": {
                        "rpc": f"/{name}/rpc",
                        "events": f"/{name}/events",
                        "ws": f"/{name}/ws"
                    },
                    "agent_card": f"{base_url}/.well-known/agent.json",
                    "handler_agent_card": f"{base_url}/{name}/.well-known/agent.json"
                }
            return handler_health
        
        # Agent card endpoint using function factory to properly capture handler_name
        def create_agent_card_endpoint(name):
            @app.get(f"/{name}/.well-known/agent.json", include_in_schema=False)
            async def handler_agent_card(request: Request):
                """Return the agent card for a specific handler."""
                # Generate base URL - for handler-specific URL, include the handler name
                base_url = str(request.base_url).rstrip('/')
                handler_url = f"{base_url}"  # Base URL already includes the handler name in path
                
                # Generate agent cards if not already done
                if not hasattr(app.state, "agent_cards"):
                    app.state.agent_cards = get_agent_cards(
                        app.state.handlers_config, 
                        base_url.replace(f"/{name}", "")  # Remove handler name from base URL
                    )
                
                # Return the agent card for the handler
                if name in app.state.agent_cards:
                    card_dict = app.state.agent_cards[name].dict(exclude_none=True)
                    # Ensure URL is correct for this specific handler
                    card_dict["url"] = handler_url
                    return card_dict
                
                # If no card found, create a minimal one
                handler_config = app.state.handlers_config.get(name, {})
                minimal_card = {
                    "name": handler_config.get("name", name.replace("_", " ").title()),
                    "description": f"A2A handler for {name}",
                    "url": handler_url,
                    "version": "1.0.0",
                    "capabilities": {
                        "streaming": True,
                        "pushNotifications": False
                    },
                    "authentication": {
                        "schemes": ["None"]
                    },
                    "defaultInputModes": ["text/plain"],
                    "defaultOutputModes": ["text/plain"],
                    "skills": [{
                        "id": f"{name}-default",
                        "name": name.replace("_", " ").title(),
                        "description": f"Default capability for {name}",
                        "tags": [name]
                    }]
                }
                return minimal_card
            return handler_agent_card
        
        # Create and add the endpoints
        create_health_endpoint(handler_name)
        create_agent_card_endpoint(handler_name)

    return app

# Default app (only EchoHandler)
app = create_app()