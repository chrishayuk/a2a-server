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

    # Register custom handlers first, if provided
    if custom_handlers:
        custom_handler_names = []
        default_handler_name = None
        
        for handler in custom_handlers:
            is_default = default_handler is not None and handler is default_handler
            manager.register_handler(handler, default=is_default)
            
            if is_default:
                default_handler_name = handler.name
            else:
                custom_handler_names.append(handler.name)
            
            # Log individual handlers at debug level
            logger.debug(f"Registered custom handler: {handler.name}{' (default)' if is_default else ''}")
        
        # Log a summary at info level
        if default_handler_name:
            logger.info(f"Registered custom handlers: {default_handler_name} (default){', ' + ', '.join(custom_handler_names) if custom_handler_names else ''}")
        elif custom_handler_names:
            logger.info(f"Registered custom handlers: {', '.join(custom_handler_names)}")

    # Register task handlers from discovery if enabled
    if use_handler_discovery:
        logger.info("Using automatic handler discovery")
        # Only set a default handler from discovery if no custom default was provided
        discovery_default = None if default_handler else EchoHandler
        register_discovered_handlers(
            manager, 
            packages=handler_packages,
            default_handler_class=discovery_default.__class__ if discovery_default else None
        )
    elif not custom_handlers:
        # If no discovery and no custom handlers, register at least EchoHandler as fallback
        logger.info("Using manual handler registration")
        manager.register_handler(EchoHandler(), default=(default_handler is None))
        logger.debug("Registered EchoHandler as default" if default_handler is None else "Registered EchoHandler")
    
    # Register JSON-RPC methods
    register_methods(protocol, manager)
    logger.debug("Registered JSON-RPC methods")

    # Create and configure the FastAPI app
    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent communication server with JSON-RPC over multiple transports",
    )
    
    # Setup all transport layers
    setup_http(app, protocol)
    setup_ws(app, protocol, event_bus)
    setup_sse(app, event_bus)
    logger.debug("Set up HTTP, WebSocket, and SSE transports")

    return app


# Default application instance
app = create_app()