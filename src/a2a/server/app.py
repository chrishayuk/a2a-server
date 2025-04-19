# a2a/server/app.py
from fastapi import FastAPI
import logging

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
    handlers: list[TaskHandler] | None = None,
    *,
    use_discovery: bool = False,
    handler_packages: list[str] | None = None
) -> FastAPI:
    """
    Create and configure the FastAPI application with A2A components.

    Args:
        handlers: Optional list of TaskHandler instances. If provided,
                  the first is registered as the default, others as non-default.
        use_discovery: If True and no handlers given, automatically discover handlers.
        handler_packages: Packages to search for discovery (when use_discovery=True).

    Returns:
        Configured FastAPI app with HTTP, WS, and SSE transports.
    """
    event_bus = EventBus()
    manager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()

    if handlers:
        default = handlers[0]
        for h in handlers:
            is_default = (h is default)
            manager.register_handler(h, default=is_default)
            logger.debug(f"Registered handler: {h.name}{' (default)' if is_default else ''}")
        logger.info(f"Registered {len(handlers)} handler(s) (default: {default.name})")
    elif use_discovery:
        logger.info("Discovering handlers automatically")
        register_discovered_handlers(manager, packages=handler_packages)
    else:
        logger.info("No handlers provided; using fallback EchoHandler")
        manager.register_handler(EchoHandler(), default=True)

    # Register JSON-RPC methods
    register_methods(protocol, manager)
    logger.debug("JSON-RPC methods registered")

    # Build the FastAPI application
    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent communication server with JSON-RPC over HTTP, WS, and SSE",
    )

    # Wire up transports
    setup_http(app, protocol)
    setup_ws(app, protocol, event_bus)
    setup_sse(app, event_bus)
    logger.debug("Configured HTTP, WebSocket, and SSE transports")

    return app


# Default app instance (echo handler only)
app = create_app()