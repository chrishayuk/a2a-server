# a2a/server/app.py
"""
Main FastAPI application factory for the A2A server.
Configures the JSON-RPC protocol, task manager, event bus, and all transports.
"""
from fastapi import FastAPI

# a2a imports
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.task_manager import TaskManager
from a2a.server.pubsub import EventBus
from a2a.server.methods import register_methods
from a2a.server.transport import setup_http, setup_ws, setup_sse


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application with all A2A components.
    
    Returns:
        FastAPI: Configured application instance with HTTP, WS, and SSE endpoints
    """
    # Create the core components
    event_bus = EventBus()
    manager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()

    # Register JSON-RPC methods
    register_methods(protocol, manager)

    # Create and configure the FastAPI app
    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent communication server with JSON-RPC over multiple transports",
    )
    
    # Setup all transport layers
    setup_http(app, protocol)
    setup_ws(app, protocol, event_bus)
    setup_sse(app, event_bus)

    return app


# Default application instance
app = create_app()