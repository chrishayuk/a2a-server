# File: a2a/server/app.py

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import a2a.server.diagnosis.debug_events as debug_events
from a2a.server.diagnosis.flow_diagnosis import apply_flow_tracing
from a2a.server.pubsub import EventBus
from a2a.server.tasks.discovery import register_discovered_handlers
from a2a.server.tasks.handlers.echo_handler import EchoHandler
from a2a.server.tasks.task_handler import TaskHandler
from a2a.server.tasks.task_manager import TaskManager
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.methods import register_methods
from a2a.server.agent_card import get_agent_cards

# our new route modules
from a2a.server.routes import debug as _debug_routes
from a2a.server.routes import health as _health_routes
from a2a.server.routes import handlers as _handler_routes

# for root‐level SSE and agent‐card
from a2a.server.transport.sse import _create_sse_response, setup_sse
from a2a.server.transport.http import setup_http
from a2a.server.transport.ws import setup_ws
from a2a.server.agent_card import get_agent_cards

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def create_app(
    handlers: Optional[List[TaskHandler]] = None,
    *,
    use_discovery: bool = False,
    handler_packages: Optional[List[str]] = None,
    handlers_config: Optional[Dict[str, Dict[str, Any]]] = None,
    enable_flow_diagnosis: bool = False,
    docs_url: Optional[str] = None,
    redoc_url: Optional[str] = None,
    openapi_url: Optional[str] = None,
) -> FastAPI:
    """
    Build the A2A server with JSON‑RPC, SSE and WebSocket transports.

    Debug routes are only mounted when enable_flow_diagnosis=True.
    """

    logger.info("Initializing A2A server components")

    # ── Event bus & optional tracing ────────────────────────────────────
    event_bus = EventBus()
    monitor_coro = None
    if enable_flow_diagnosis:
        logger.info("Enabling flow diagnostics")
        debug_events.enable_debug()
        event_bus = debug_events.add_event_tracing(event_bus)

        # apply tracing to HTTP, SSE & get monitor coroutine
        http_mod = __import__("a2a.server.transport.http", fromlist=["setup_http"])
        sse_mod = __import__("a2a.server.transport.sse", fromlist=["setup_sse"])
        monitor_coro = apply_flow_tracing(None, http_mod, sse_mod, event_bus)

    # ── Task manager & protocol ────────────────────────────────────────
    task_manager = TaskManager(event_bus)
    if enable_flow_diagnosis:
        task_manager = debug_events.trace_task_manager(task_manager)

    protocol = JSONRPCProtocol()

    # ── Handler registration ───────────────────────────────────────────
    if handlers:
        default = handlers[0]
        for h in handlers:
            task_manager.register_handler(h, default=(h is default))
            logger.info("Registered handler %s%s",
                        h.name, " (default)" if h is default else "")
    elif use_discovery:
        logger.info("Using discovery for handlers in %s", handler_packages)
        register_discovered_handlers(task_manager, packages=handler_packages)
    else:
        logger.info("No handlers specified → using EchoHandler")
        task_manager.register_handler(EchoHandler(), default=True)

    if enable_flow_diagnosis:
        debug_events.verify_handlers(task_manager)

    if handlers_config:
        logger.debug("Handler configurations: %r", handlers_config)

    register_methods(protocol, task_manager)

    # ── Create FastAPI + CORS ──────────────────────────────────────────
    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent JSON-RPC over HTTP, SSE & WebSocket",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # stash for route modules & hooks
    app.state.handlers_config = handlers_config or {}
    app.state.event_bus = event_bus
    app.state.task_manager = task_manager

    # ── Transports ────────────────────────────────────────────────────
    logger.info("Setting up transport layers")
    setup_http(app, protocol, task_manager, event_bus)
    setup_ws(app, protocol, event_bus, task_manager)
    setup_sse(app, event_bus, task_manager)

    # ── Root‐level health, SSE & agent‐card ──────────────────────────

    @app.get("/", include_in_schema=False)
    async def root_health(request: Request, task_ids: Optional[List[str]] = Query(None)):
        if task_ids:
            # upgrade to SSE streaming
            return await _create_sse_response(app.state.event_bus, task_ids)
        return {
            "service": "A2A Server",
            "endpoints": {
                "rpc": "/rpc",
                "events": "/events",
                "ws": "/ws",
                "agent_card": "/agent-card.json",
            },
        }

    @app.get("/events", include_in_schema=False)
    async def root_events(request: Request, task_ids: Optional[List[str]] = Query(None)):
        """
        Upgrade GET /events?task_ids=<id1>&task_ids=<id2> to an SSE stream
        of all matching task events.
        """
        return await _create_sse_response(app.state.event_bus, task_ids)

    @app.get("/agent-card.json", include_in_schema=False)
    async def root_agent_card(request: Request):
        base = str(request.base_url).rstrip("/")
        cards = get_agent_cards(handlers_config or {}, base)
        default = next(iter(cards.values()), None)
        if default:
            return default.dict(exclude_none=True)
        raise HTTPException(status_code=404, detail="No agent card available")

    # ── Startup/shutdown for flow diagnosis monitor ───────────────────────
    if monitor_coro:
        import asyncio

        @app.on_event("startup")
        async def _start_monitor():
            app.state._monitor_task = asyncio.create_task(monitor_coro())

        @app.on_event("shutdown")
        async def _stop_monitor():
            t = getattr(app.state, "_monitor_task", None)
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    # ── Mount modular routes ───────────────────────────────────────────
    if enable_flow_diagnosis:
        _debug_routes.register_debug_routes(app, event_bus, task_manager)

    _health_routes.register_health_routes(app, task_manager, handlers_config)
    _handler_routes.register_handler_routes(app, task_manager, handlers_config)

    logger.info("A2A server ready")
    return app
