# File: a2a/server/app.py
from fastapi import FastAPI
import logging
from typing import Optional, List

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
    Build the FastAPI app, register either your handlers or discover them.
    - If `handlers` is given, the first is default, the rest non-default.
    - Otherwise if `use_discovery`, auto‑discover.
    - Else fall back to EchoHandler.
    """
    eb = EventBus()
    mgr = TaskManager(eb)
    proto = JSONRPCProtocol()

    if handlers:
        default = handlers[0]
        for h in handlers:
            is_def = (h is default)
            mgr.register_handler(h, default=is_def)
            logger.debug(f"Registered handler: {h.name}{' (default)' if is_def else ''}")
        logger.info(f"Registered {len(handlers)} handler(s), default='{default.name}'")

    elif use_discovery:
        logger.info("Discovering handlers automatically")
        register_discovered_handlers(mgr, packages=handler_packages)

    else:
        logger.info("No handlers → using EchoHandler fallback")
        mgr.register_handler(EchoHandler(), default=True)

    # JSON‑RPC wiring
    register_methods(proto, mgr)
    logger.debug("JSON-RPC methods registered")

    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent JSON‑RPC over HTTP, WS, SSE",
    )
    # Register transports
    setup_http(app, proto)
    setup_ws(app, proto, eb)
    setup_sse(app, eb)
    logger.debug("Transports configured (HTTP, WS, SSE)")

    # Health check endpoint on each sub-app (both with and without trailing slash)
    @app.get("/", include_in_schema=False)
    async def _health():
        """Return the RPC and SSE endpoints."""
        return {"rpc": "/rpc", "events": "/events"}

    @app.get("", include_in_schema=False)
    async def _health_noslash():
        """Alias health without trailing slash."""
        return {"rpc": "/rpc", "events": "/events"}

    return app

# default app (only EchoHandler)
app = create_app()