# a2a_server/app.py
from __future__ import annotations
"""Application factory for the Agent-to-Agent (A2A) server.

Additions - May 2025
~~~~~~~~~~~~~~~~~~~~
* **Security headers** - small hardening shim that is always on.
* **Token-guard** - simple shared-secret check for *admin* routes.
* **Rate-limit** - in-memory sliding-window (30req / 60s default), keyed by
  remote IP.  Adjust via ``A2A_RATE_LIMIT`` / ``A2A_RATE_WINDOW`` env vars.
* **Debug/metrics lockdown** - ``/debug*`` and ``/metrics`` are now protected
  with the token guard as well.
* **Shared session-store** - single instance created via
  :func:`a2a_server.session_store_factory.build_session_store` and injected
  into app state for handlers / routes.
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

# ── internal imports ───────────────────────────────────────────────────────
import a2a_server.diagnosis.debug_events as debug_events
from a2a_server.diagnosis.flow_diagnosis import apply_flow_tracing
from a2a_server.pubsub import EventBus
from a2a_server.tasks.discovery import register_discovered_handlers
from a2a_server.tasks.handlers.echo_handler import EchoHandler
from a2a_server.tasks.task_handler import TaskHandler
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

# 🔹 session-store factory
from a2a_server.session_store_factory import build_session_store

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
# admin-token guard + rate-limit helpers
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = os.getenv("A2A_ADMIN_TOKEN")
_MAX_REQ = int(os.getenv("A2A_RATE_LIMIT", "30"))
_WINDOW = int(os.getenv("A2A_RATE_WINDOW", "60"))  # seconds

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


class _InMemoryRateLimiter:  # pylint: disable=too-few-public-methods
    """Very small sliding-window rate limiter (per-IP)."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = self._hits.setdefault(key, [])
            while bucket and now - bucket[0] > self._window:
                bucket.pop(0)
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True


_rate_limiter = _InMemoryRateLimiter(_MAX_REQ, _WINDOW)

# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------


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
    """Return a fully-wired :class:`fastapi.FastAPI` instance for the A2A server."""

    logger.info("Initializing A2A server components")

    # ── Event bus (+ optional tracing) ─────────────────────────────────
    event_bus: EventBus = EventBus()
    monitor_coro = None
    if enable_flow_diagnosis:
        logger.info("Enabling flow diagnostics")
        debug_events.enable_debug()
        event_bus = debug_events.add_event_tracing(event_bus)

        http_mod = __import__("a2a_server.transport.http", fromlist=["setup_http"])
        sse_mod = __import__("a2a_server.transport.sse", fromlist=["setup_sse"])
        monitor_coro = apply_flow_tracing(None, http_mod, sse_mod, event_bus)

    # ── 🔹 Build shared session store ──────────────────────────────────
    sess_cfg = (handlers_config or {}).get("_session_store", {})
    session_store = session_store = build_session_store()
    logger.info("Session store initialised via %s", session_store.__class__.__name__)

    # ── Task-manager + JSON-RPC proto ──────────────────────────────────
    task_manager: TaskManager = TaskManager(event_bus)
    if enable_flow_diagnosis:
        task_manager = debug_events.trace_task_manager(task_manager)

    protocol = JSONRPCProtocol()

    # ── Handler registration ──────────────────────────────────────────
    if handlers:
        default = handlers[0]
        for h in handlers:
            task_manager.register_handler(h, default=(h is default))
            logger.info("Registered handler %s%s", h.name, " (default)" if h is default else "")
    elif use_discovery:
        logger.info("Using discovery for handlers in %s", handler_packages)
        register_discovered_handlers(task_manager, packages=handler_packages, extra_kwargs={"session_store": session_store})
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # ------------------------------------------------------------------
    # rate-limit middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):  # noqa: D401
        key = request.client.host if request.client else "unknown"
        if not await _rate_limiter.is_allowed(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
            )
        return await call_next(request)

    # ------------------------------------------------------------------
    # admin-token guard middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def _admin_guard(request: Request, call_next):  # noqa: D401
        if request.url.path.startswith(_PROTECTED_PREFIXES):
            require_admin_token(request)
        return await call_next(request)

    # ------------------------------------------------------------------
    # security headers middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # noqa: D401
        resp: Response = await call_next(request)
        resp.headers.update(_SEC_HEADERS)
        return resp

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

    # ── Flow-diagnosis monitor task ──────────────────────────────────
    if monitor_coro:
        @app.on_event("startup")
        async def _start_monitor():  # noqa: D401
            app.state._monitor_task = asyncio.create_task(monitor_coro())

        @app.on_event("shutdown")
        async def _stop_monitor():  # noqa: D401
            t = getattr(app.state, "_monitor_task", None)
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    # ── Extra route modules ──────────────────────────────────────────
    DEBUG_A2A = os.getenv("DEBUG_A2A", "0") == "1"
    if enable_flow_diagnosis and DEBUG_A2A:
        _debug_routes.register_debug_routes(app, event_bus, task_manager)

    _health_routes.register_health_routes(app, task_manager, handlers_config)
    _handler_routes.register_handler_routes(app, task_manager, handlers_config)

    logger.info("A2A server ready")
    return app
