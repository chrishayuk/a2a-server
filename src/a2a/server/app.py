# a2a/server/app.py
from fastapi import FastAPI
import logging

# a2a imports
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.tasks.task_manager import TaskManager
from a2a.server.pubsub import EventBus
from a2a.server.methods import register_methods
from a2a.server.transport import setup_http, setup_ws, setup_sse
from a2a.server.tasks.discovery import register_discovered_handlers
from a2a.server.tasks.handlers.echo_handler import EchoHandler

logger = logging.getLogger(__name__)

def create_app(
    use_handler_discovery: bool = True,
    handler_packages: list[str] = None,
    custom_handlers: list = None,
    default_handler = None
) -> FastAPI:
    """
    Create and configure the FastAPI application with all A2A components.
    
    Args:
        use_handler_discovery: Whether to use automatic handler discovery
        handler_packages: Optional list of packages to search for handlers
        custom_handlers: Optional list of handler instances to register manually
        default_handler: Optional handler to use as default
    
    Returns:
        FastAPI: Configured application instance with HTTP, WS, and SSE endpoints
    """
    # Create the core components
    event_bus = EventBus()
    manager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()

    # Register task handlers
    if use_handler_discovery:
        logger.info("Using automatic handler discovery")
        register_discovered_handlers(
            manager, 
            packages=handler_packages,
            default_handler_class=EchoHandler if default_handler is None else default_handler.__class__
        )
    else:
        # Register handlers manually
        logger.info("Using manual handler registration")
        manager.register_handler(EchoHandler(), default=(default_handler is None))
    
    # Register any additional custom handlers
    if custom_handlers:
        for handler in custom_handlers:
            is_default = default_handler is not None and handler.__class__ is default_handler.__class__
            manager.register_handler(handler, default=is_default)
            logger.info(f"Registered custom handler: {handler.name}")
    
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