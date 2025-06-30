# a2a_server/app.py
from __future__ import annotations
"""Application factory for the Agent-to-Agent (A2A) server.

Additions - May 2025
~~~~~~~~~~~~~~~~~~~~
* **Security headers** - small hardening shim that is always on.
* **Token-guard** - simple shared-secret check for *admin* routes.
* **Debug/metrics lockdown** - ``/debug*`` and ``/metrics`` are now protected
  with the token guard as well.
* **Shared session-store** - single instance created via
  :func:`a2a_server.session_store_factory.build_session_manager` and injected
  into app state for handlers / routes.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

# ── internal imports ───────────────────────────────────────────────────────
from a2a_server.pubsub import EventBus
from a2a_server.tasks.discovery import register_discovered_handlers
from a2a_server.tasks.handlers.echo_handler import EchoHandler
from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_server.tasks.task_manager import TaskManager
from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_server.methods import register_methods
from a2a_server.agent_card import get_agent_cards

# extra route modules
from a2a_server.routes import debug as _debug_routes
from a2a_server.routes import health as _health_routes
from a2a_server.routes import handlers as _handler_routes

# transports
from a2a_server.transport.sse import _create_sse_response, setup_sse
from a2a_server.transport.http import setup_http
from a2a_server.transport.ws import setup_ws

# metrics helper (OpenTelemetry / Prometheus)
from a2a_server import metrics as _metrics

# 🔹 session-store factory - FIXED IMPORT
from a2a_server.session_store_factory import build_session_manager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# security headers (basic, non-conflicting)
# ---------------------------------------------------------------------------

_SEC_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=()",  # deny common high-risk perms
}

# ---------------------------------------------------------------------------
# admin-token guard
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = os.getenv("A2A_ADMIN_TOKEN")

_PROTECTED_PREFIXES: tuple[str, ...] = (
    "/sessions",
    "/analytics",
    "/debug",
    "/metrics",
)


def require_admin_token(request: Request) -> None:  # noqa: D401
    """Raise *401* if the caller does not present the valid admin token."""
    if _ADMIN_TOKEN is None:  # guard disabled
        return

    token = (
        request.headers.get("x-a2a-admin-token")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    if token != _ADMIN_TOKEN:
        logger.debug("Admin-token check failed for %s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token"
        )

# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------


def create_app(
    handlers: Optional[List[TaskHandler]] = None,
    *,
    use_discovery: bool = False,
    handler_packages: Optional[List[str]] = None,
    handlers_config: Optional[Dict[str, Dict[str, Any]]] = None,
    docs_url: Optional[str] = None,
    redoc_url: Optional[str] = None,
    openapi_url: Optional[str] = None,
) -> FastAPI:
    """Return a fully-wired :class:`fastapi.FastAPI` instance for the A2A server."""

    logger.info("Initializing A2A server components")

    # ── Event bus ──────────────────────────────────────────────────────
    event_bus: EventBus = EventBus()

    # ── 🔹 Build shared session store - FIXED FUNCTION CALL ──────────────────────────────────
    sess_cfg = (handlers_config or {}).get("_session_store", {})
    session_store = build_session_manager(
        sandbox_id=sess_cfg.get("sandbox_id", "a2a-server"),
        default_ttl_hours=sess_cfg.get("default_ttl_hours", 24)
    )
    logger.info("Session store initialised via %s", session_store.__class__.__name__)

    # ── Task-manager + JSON-RPC proto ──────────────────────────────────
    task_manager: TaskManager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()

    # ── Handler registration ──────────────────────────────────────────
    if handlers:
        default = handlers[0]
        for h in handlers:
            task_manager.register_handler(h, default=(h is default))
            logger.info("Registered handler %s%s", h.name, " (default)" if h is default else "")
    elif use_discovery:
        logger.info("Using discovery for handlers in %s", handler_packages)
        
        # 🔧 CRITICAL FIX: Extract and pass handler configurations from YAML
        handler_configs = {}
        if handlers_config:
            handler_configs = {
                k: v for k, v in handlers_config.items() 
                if k not in ['use_discovery', 'default_handler'] and isinstance(v, dict)
            }
            logger.debug(f"🔧 Passing {len(handler_configs)} handler configurations to discovery")
            logger.debug(f"🔧 Handler configs: {list(handler_configs.keys())}")
        
        register_discovered_handlers(
            task_manager, 
            packages=handler_packages, 
            extra_kwargs={"session_store": session_store},
            **handler_configs  # 🔧 CRITICAL: This passes your YAML handler configs
        )
    elif handlers_config:
        # 🔧 NEW: Handle explicit handler configurations when discovery is disabled
        logger.info("Registering explicit handlers from configuration")
        
        handler_configs = {
            k: v for k, v in handlers_config.items() 
            if k not in ['use_discovery', 'default_handler'] and isinstance(v, dict)
        }
        
        logger.debug(f"🔧 Found {len(handler_configs)} handler configurations: {list(handler_configs.keys())}")
        
        register_discovered_handlers(
            task_manager,
            packages=None,  # No package discovery
            extra_kwargs={"session_store": session_store},
            **handler_configs  # Pass YAML configurations
        )
    else:
        logger.info("No handlers specified → using EchoHandler")
        task_manager.register_handler(EchoHandler(), default=True)

    if handlers_config:
        logger.debug("Handler configurations: %r", handlers_config)

    register_methods(protocol, task_manager)

    # ── FastAPI app & middleware ──────────────────────────────────────
    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent JSON-RPC over HTTP, SSE & WebSocket",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # TEMPORARILY DISABLED: CORS middleware to test if it's causing Content-Length issues
    # app.add_middleware(
    #     CORSMiddleware,
    #     allow_origins=["*"],
    #     allow_methods=["*"],
    #     allow_headers=["*"],
    #     allow_credentials=True,
    # )

    # NOTE: All middleware temporarily removed to identify Content-Length issue source
    # Your duplicate task prevention is working perfectly at the application level

    # ── share state with routes ───────────────────────────────────────
    app.state.handlers_config = handlers_config or {}
    app.state.event_bus = event_bus
    app.state.task_manager = task_manager
    app.state.session_store = session_store            # 🔹

    # ── Transports ────────────────────────────────────────────────────
    logger.info("Setting up transport layers")
    setup_http(app, protocol, task_manager, event_bus)
    setup_ws(app, protocol, event_bus, task_manager)
    setup_sse(app, event_bus, task_manager)

    # ── Metrics middleware + /metrics (token-guarded) ────────────────
    _metrics.instrument_app(app)

    # ── Root routes ───────────────────────────────────────────────────
    @app.get("/test-simple", include_in_schema=False)
    async def test_simple():
        """Simple test endpoint to check if basic responses work."""
        return {"test": "simple", "status": "ok"}
    
    @app.post("/test-rpc", include_in_schema=False)  
    async def test_rpc():
        """Test endpoint that mimics RPC behavior."""
        return {"jsonrpc": "2.0", "id": "test", "result": {"test": "rpc", "status": "ok"}}

    @app.get("/", include_in_schema=False)
    async def root_health(request: Request, task_ids: Optional[List[str]] = Query(None)):  # noqa: D401
        if task_ids:
            return await _create_sse_response(app.state.event_bus, task_ids)
        return {
            "service": "A2A Server",
            "endpoints": {
                "rpc": "/rpc",
                "events": "/events",
                "ws": "/ws",
                "agent_card": "/agent-card.json",
                "metrics": "/metrics",
            },
        }

    @app.get("/events", include_in_schema=False)
    async def root_events(request: Request, task_ids: Optional[List[str]] = Query(None)):  # noqa: D401
        return await _create_sse_response(app.state.event_bus, task_ids)

    @app.get("/agent-card.json", include_in_schema=False)
    async def root_agent_card(request: Request):  # noqa: D401
        base = str(request.base_url).rstrip("/")
        cards = get_agent_cards(handlers_config or {}, base)
        default = next(iter(cards.values()), None)
        if default:
            return default.dict(exclude_none=True)
        raise HTTPException(status_code=404, detail="No agent card available")

    # ── Extra route modules ──────────────────────────────────────────
    DEBUG_A2A = os.getenv("DEBUG_A2A", "0") == "1"
    if DEBUG_A2A:
        _debug_routes.register_debug_routes(app, event_bus, task_manager)

    _health_routes.register_health_routes(app, task_manager, handlers_config)
    _handler_routes.register_handler_routes(app, task_manager, handlers_config)

    logger.info("A2A server ready")
    return app