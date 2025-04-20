# File: a2a/server/app.py
"""
A2A server application factory with explicit route registration.
"""
from fastapi import FastAPI, Request
import logging
from typing import Optional, List, Dict

from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.tasks.task_manager import TaskManager
from a2a.server.pubsub import EventBus
from a2a.server.methods import register_methods
from a2a.server.transport import setup_http, setup_ws, setup_sse
from a2a.server.tasks.discovery import register_discovered_handlers
from a2a.server.tasks.handlers.echo_handler import EchoHandler
from a2a.server.tasks.task_handler import TaskHandler

logger = logging.getLogger(__name__)

def create_app(
    handlers: Optional[List[TaskHandler]] = None,
    *,
    use_discovery: bool = False,
    handler_packages: Optional[List[str]] = None
) -> FastAPI:
    """
    Build the FastAPI app with direct handler routing using explicit routes.
    
    Args:
        handlers: Optional list of handlers to register (first is default)
        use_discovery: Whether to auto-discover handlers
        handler_packages: Optional packages to search for handlers
        
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
    
    # Add a root health check endpoint
    @app.get("/", include_in_schema=False)
    async def health_check():
        """Root health check endpoint."""
        default_handler = task_manager.get_default_handler()
        handlers = task_manager.get_handlers()
        
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
            }
        }
    
    # Add health check endpoints for each handler first (before transport setup)
    for handler_name in task_manager.get_handlers():
        # Use a function to capture handler_name value properly
        def create_health_endpoint(name):
            @app.get(f"/{name}", include_in_schema=False)
            async def handler_health():
                """Handler-specific health check."""
                return {
                    "handler": name,
                    "endpoints": {
                        "rpc": f"/{name}/rpc",
                        "events": f"/{name}/events",
                        "ws": f"/{name}/ws"
                    }
                }
            return handler_health
        
        # Create and add the endpoint
        create_health_endpoint(handler_name)
    
    # Register transports with explicit endpoint registration for each handler
    setup_http(app, protocol, task_manager)
    setup_ws(app, protocol, event_bus, task_manager)
    setup_sse(app, event_bus, task_manager)
    logger.debug("Transports configured with direct handler mounting")

    return app

# Default app (only EchoHandler)
app = create_app()