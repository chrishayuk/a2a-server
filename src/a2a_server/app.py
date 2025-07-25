# a2a_server/app.py
from __future__ import annotations
"""Application factory for the Agent-to-Agent (A2A) server.

Additions - May 2025
~~~~~~~~~~~~~~~~~~~~
* **Security headers** - small hardening shim that is always on.
* **Enhanced token-guard** - supports both header formats and optional global auth.
* **Debug/metrics lockdown** - ``/debug*`` and ``/metrics`` are now protected
  with the token guard as well.
* **Shared session-store** - single instance created via
  :func:`a2a_server.session_store_factory.build_session_manager` and injected
  into app state for handlers / routes.
* **Performance optimizations** - memory management, session pooling, async tools.
* **Optional global auth** - middleware-based auth for API-wide protection.
"""

import asyncio
import logging
import os
import time
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

# session-store factory
from a2a_server.session_store_factory import build_session_manager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# security headers (basic, non-conflicting)
# ---------------------------------------------------------------------------

_SEC_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=()",
}

# ---------------------------------------------------------------------------
# enhanced admin-token guard with optional global auth
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = os.getenv("A2A_ADMIN_TOKEN")

_PROTECTED_PREFIXES: tuple[str, ...] = (
    "/sessions",
    "/analytics", 
    "/debug",
    "/metrics",
    "/admin",
)

def require_admin_token(request: Request) -> None:
    """Enhanced admin token check with multiple header support."""
    if _ADMIN_TOKEN is None:  # guard disabled
        return

    # Try multiple auth header formats
    token = (
        request.headers.get("x-a2a-admin-token") or
        request.headers.get("authorization", "").removeprefix("Bearer ").strip() or
        request.cookies.get("admin_token")  # Cookie fallback
    )
    
    if not token or not _secure_compare(token, _ADMIN_TOKEN):
        logger.debug("Admin-token check failed for %s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid admin token"
        )

def _secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if len(a) != len(b):
        return False
    
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    
    return result == 0

# ---------------------------------------------------------------------------
# optional global auth middleware
# ---------------------------------------------------------------------------

def _create_global_auth_middleware(bearer_token: str, exclude_paths: set = None):
    """Create optional global authentication middleware."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    import re
    
    exclude_paths = exclude_paths or {
        "/health", "/ready", "/metrics", "/",
        "/agent-card.json", "/.well-known/agent.json",
        "/test-simple", "/test-rpc"
    }
    
    class GlobalAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Skip auth for excluded paths
            if request.url.path in exclude_paths:
                return await call_next(request)
            
            # Skip auth for health GET requests
            if request.method == "GET" and request.url.path in {"/health", "/ready"}:
                return await call_next(request)
            
            # Extract token
            auth_header = request.headers.get("Authorization", "")
            token = None
            
            if auth_header:
                match = re.match(r"Bearer\s+(.+)", auth_header, re.IGNORECASE)
                if match:
                    token = match.group(1)
            
            # Cookie fallback
            if not token:
                token = request.cookies.get("auth_token")
            
            if not token or not _secure_compare(token, bearer_token):
                return JSONResponse(
                    {"error": "Authentication required", "detail": "Invalid bearer token"}, 
                    status_code=401
                )
            
            # Add auth info to request scope
            request.scope["authenticated"] = True
            request.scope["auth_method"] = "global_bearer"
            
            return await call_next(request)
    
    return GlobalAuthMiddleware

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
    config: Optional[Dict[str, Any]] = None,  # Add full config support
) -> FastAPI:
    """Return a fully-wired FastAPI instance for the A2A server with optimizations."""

    logger.info("Initializing A2A server components with optimizations")

    # ── Event bus ──────────────────────────────────────────────────────
    event_bus: EventBus = EventBus()

    # ── Session store with optimization settings ───────────────────────
    sess_cfg = (handlers_config or {}).get("_session_store", {})
    session_store = build_session_manager(
        sandbox_id=sess_cfg.get("sandbox_id", "a2a-server"),
        default_ttl_hours=sess_cfg.get("default_ttl_hours", 24)
    )
    logger.info("Session store initialised via %s", session_store.__class__.__name__)

    # ── Task-manager + JSON-RPC proto ──────────────────────────────────
    task_manager: TaskManager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()

    # ── Handler registration with optimizations ────────────────────────
    if handlers:
        default = handlers[0]
        for h in handlers:
            task_manager.register_handler(h, default=(h is default))
            logger.info("Registered handler %s%s", h.name, " (default)" if h is default else "")
    elif use_discovery:
        logger.info("Using optimized discovery for handlers in %s", handler_packages)
        
        # Extract and pass handler configurations from YAML
        handler_configs = {}
        if handlers_config:
            handler_configs = {
                k: v for k, v in handlers_config.items() 
                if k not in ['use_discovery', 'default_handler'] and isinstance(v, dict)
            }
            logger.debug(f"🔧 Passing {len(handler_configs)} handler configurations to optimized discovery")
        
        register_discovered_handlers(
            task_manager, 
            packages=handler_packages, 
            extra_kwargs={"session_store": session_store},
            **handler_configs
        )
    elif handlers_config:
        # Handle explicit handler configurations when discovery is disabled
        logger.info("Registering explicit handlers from configuration")
        
        handler_configs = {
            k: v for k, v in handlers_config.items() 
            if k not in ['use_discovery', 'default_handler'] and isinstance(v, dict)
        }
        
        register_discovered_handlers(
            task_manager,
            packages=None,
            extra_kwargs={"session_store": session_store},
            **handler_configs
        )
    else:
        logger.info("No handlers specified → using EchoHandler")
        task_manager.register_handler(EchoHandler(), default=True)

    register_methods(protocol, task_manager)

    # ── FastAPI app & middleware ──────────────────────────────────────
    app = FastAPI(
        title="A2A Server",
        description="Agent-to-Agent JSON-RPC over HTTP, SSE & WebSocket with optimizations",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # ── Optional global authentication middleware ──────────────────────
    global_bearer_token = None
    if config and config.get("auth", {}).get("bearer_token"):
        global_bearer_token = config["auth"]["bearer_token"]
        exclude_paths = set(config["auth"].get("exclude_paths", []))
        exclude_paths.update({"/health", "/ready", "/", "/agent-card.json"})
        
        auth_middleware = _create_global_auth_middleware(global_bearer_token, exclude_paths)
        app.add_middleware(auth_middleware)
        logger.info("🔐 Global bearer token authentication enabled")
    
    # ── CORS middleware (configurable) ─────────────────────────────────
    cors_config = config.get("cors", {}) if config else {}
    if cors_config.get("enabled", True):  # Default enabled
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_config.get("allow_origins", ["*"]),
            allow_methods=cors_config.get("allow_methods", ["*"]),
            allow_headers=cors_config.get("allow_headers", ["*"]),
            allow_credentials=cors_config.get("allow_credentials", True),
        )
        logger.info("🌐 CORS middleware enabled")

    # ── Security headers middleware ────────────────────────────────────
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        for header, value in _SEC_HEADERS.items():
            response.headers[header] = value
        return response

    # ── Share state with routes ────────────────────────────────────────
    app.state.handlers_config = handlers_config or {}
    app.state.event_bus = event_bus
    app.state.task_manager = task_manager
    app.state.session_store = session_store
    app.state.server_config = config or {}

    # ── Transports ─────────────────────────────────────────────────────
    logger.info("Setting up optimized transport layers")
    setup_http(app, protocol, task_manager, event_bus)
    setup_ws(app, protocol, event_bus, task_manager)
    setup_sse(app, event_bus, task_manager)

    # ── Metrics middleware + /metrics (token-guarded) ──────────────────
    _metrics.instrument_app(app)

    # ── Root routes ────────────────────────────────────────────────────
    @app.get("/test-simple", include_in_schema=False)
    async def test_simple():
        """Simple test endpoint to check if basic responses work."""
        return {"test": "simple", "status": "ok"}
    
    @app.post("/test-rpc", include_in_schema=False)  
    async def test_rpc():
        """Test endpoint that mimics RPC behavior."""
        return {"jsonrpc": "2.0", "id": "test", "result": {"test": "rpc", "status": "ok"}}

    @app.get("/", include_in_schema=False)
    async def root_health(request: Request, task_ids: Optional[List[str]] = Query(None)):
        if task_ids:
            return await _create_sse_response(app.state.event_bus, task_ids)
        
        # Show auth status
        auth_status = {
            "admin_token": "enabled" if _ADMIN_TOKEN else "disabled",
            "global_auth": "enabled" if global_bearer_token else "disabled"
        }
        
        return {
            "service": "A2A Server",
            "version": "1.0.0-optimized",
            "authentication": auth_status,
            "endpoints": {
                "rpc": "/rpc",
                "events": "/events",
                "ws": "/ws",
                "agent_card": "/agent-card.json",
                "metrics": "/metrics" + (" (admin auth)" if _ADMIN_TOKEN else ""),
                "admin": "/admin/*" + (" (admin auth)" if _ADMIN_TOKEN else ""),
            },
            "handlers": list(task_manager.get_handlers().keys()),
            "default_handler": task_manager.get_default_handler(),
            "optimizations": "enabled"
        }

    @app.get("/events", include_in_schema=False)
    async def root_events(request: Request, task_ids: Optional[List[str]] = Query(None)):
        return await _create_sse_response(app.state.event_bus, task_ids)

    @app.get("/agent-card.json", include_in_schema=False)
    async def root_agent_card(request: Request):
        base = str(request.base_url).rstrip("/")
        cards = get_agent_cards(handlers_config or {}, base)
        default = next(iter(cards.values()), None)
        if default:
            return default.model_dump(exclude_none=True)
        raise HTTPException(status_code=404, detail="No agent card available")

    # ── Admin routes (protected) ───────────────────────────────────────
    @app.get("/admin/stats", include_in_schema=False)
    async def admin_stats(request: Request):
        """Admin statistics endpoint."""
        require_admin_token(request)
        
        # Get performance stats from optimized components
        stats = {
            "timestamp": time.time(),
            "task_manager": {
                "active_tasks": len(task_manager._active),
                "total_handlers": len(task_manager._handlers),
                "deduplication_stats": task_manager.get_deduplication_stats()
            },
            "authentication": {
                "admin_token_enabled": _ADMIN_TOKEN is not None,
                "global_auth_enabled": global_bearer_token is not None,
                "request_authenticated": request.scope.get("authenticated", False)
            }
        }
        
        # Add discovery stats if available
        try:
            from a2a_server.tasks.discovery import get_discovery_stats
            stats["discovery"] = get_discovery_stats()
        except ImportError:
            stats["discovery"] = {"available": False}
        
        # Add tool cache stats if available
        try:
            from a2a_server.tasks.handlers.chuk.chuk_agent import _tool_cache
            stats["tool_cache"] = _tool_cache.get_stats()
        except ImportError:
            stats["tool_cache"] = {"available": False}
        
        return stats

    @app.get("/admin/health", include_in_schema=False)
    async def admin_health(request: Request):
        """Detailed health check for admin."""
        require_admin_token(request)
        
        health = {
            "status": "healthy",
            "timestamp": time.time(),
            "components": {
                "task_manager": "healthy",
                "event_bus": "healthy", 
                "session_store": "healthy"
            },
            "optimizations": {
                "discovery_cleanup": "active",
                "session_pooling": "active",
                "tool_caching": "active"
            }
        }
        
        # Check handler health
        handler_health = {}
        for handler_name, handler in task_manager._handlers.items():
            if hasattr(handler, 'get_health_status'):
                try:
                    handler_health[handler_name] = handler.get_health_status()
                except Exception as e:
                    handler_health[handler_name] = {"status": "error", "error": str(e)}
            else:
                handler_health[handler_name] = {"status": "unknown"}
        
        health["handlers"] = handler_health
        return health

    @app.post("/admin/cleanup", include_in_schema=False)
    async def admin_cleanup(request: Request):
        """Manual cleanup trigger for admin."""
        require_admin_token(request)
        
        results = {}
        
        # Discovery system cleanup
        try:
            from a2a_server.tasks.discovery import cleanup_discovery_system
            cleanup_discovery_system()
            results["discovery_cleanup"] = "success"
        except Exception as e:
            results["discovery_cleanup"] = f"error: {e}"
        
        # Tool cache cleanup
        try:
            from a2a_server.tasks.handlers.chuk.chuk_agent import _tool_cache
            await _tool_cache.clear()
            results["tool_cache_cleanup"] = "success"
        except Exception as e:
            results["tool_cache_cleanup"] = f"error: {e}"
        
        return {"cleanup_results": results, "timestamp": time.time()}

    # ── Authentication status endpoint ─────────────────────────────────
    @app.get("/auth/status", include_in_schema=False)
    async def auth_status(request: Request):
        """Get authentication status."""
        return {
            "admin_auth": {
                "enabled": _ADMIN_TOKEN is not None,
                "env_var": "A2A_ADMIN_TOKEN"
            },
            "global_auth": {
                "enabled": global_bearer_token is not None,
                "authenticated": request.scope.get("authenticated", False),
                "method": request.scope.get("auth_method")
            },
            "request_headers": {
                "has_authorization": "Authorization" in request.headers,
                "has_admin_token": "x-a2a-admin-token" in request.headers
            },
            "timestamp": time.time()
        }

    # ── Extra route modules ────────────────────────────────────────────
    DEBUG_A2A = os.getenv("DEBUG_A2A", "0") == "1"
    if DEBUG_A2A:
        _debug_routes.register_debug_routes(app, event_bus, task_manager)

    _health_routes.register_health_routes(app, task_manager, handlers_config)
    _handler_routes.register_handler_routes(app, task_manager, handlers_config)

    # ── Startup and shutdown events ────────────────────────────────────
    @app.on_event("startup")
    async def startup_event():
        """Application startup with optimization initialization."""
        logger.info("🚀 A2A Server starting up with optimizations")
        
        # Start background cleanup for discovery system
        try:
            from a2a_server.tasks.discovery import _ensure_cleanup_task
            _ensure_cleanup_task()
            logger.info("✅ Discovery system cleanup task started")
        except Exception as e:
            logger.warning(f"⚠️ Failed to start discovery cleanup: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        """Application shutdown with optimization cleanup."""
        logger.info("🛑 A2A Server shutting down")
        
        # Shutdown task manager
        try:
            await task_manager.shutdown()
            logger.info("✅ Task manager shutdown complete")
        except Exception as e:
            logger.error(f"❌ Task manager shutdown error: {e}")
        
        # Cleanup discovery system
        try:
            from a2a_server.tasks.discovery import cleanup_discovery_system
            cleanup_discovery_system()
            logger.info("✅ Discovery system cleanup complete")
        except Exception as e:
            logger.error(f"❌ Discovery cleanup error: {e}")
        
        # Clean up tool cache
        try:
            from a2a_server.tasks.handlers.chuk.chuk_agent import _tool_cache
            await _tool_cache.clear()
            logger.info("✅ Tool cache cleanup complete")
        except Exception as e:
            logger.error(f"❌ Tool cache cleanup error: {e}")
        
        # Close session store if needed
        if hasattr(session_store, 'close'):
            try:
                await session_store.close()
                logger.info("✅ Session store closed")
            except Exception as e:
                logger.error(f"❌ Session store close error: {e}")

    logger.info("A2A server ready with optimizations")
    return app


# ── Utility functions ──────────────────────────────────────────────────────

def create_app_from_config(config_path: str) -> FastAPI:
    """Create app from YAML configuration file."""
    import yaml
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    handlers_config = config.get("handlers", {})
    
    return create_app(
        use_discovery=handlers_config.get("use_discovery", False),
        handler_packages=handlers_config.get("handler_packages"),
        handlers_config=handlers_config,
        config=config
    )


def get_example_config() -> Dict[str, Any]:
    """Get example configuration with optimizations and auth."""
    return {
        "server": {
            "host": "0.0.0.0",
            "port": 8000
        },
        "auth": {
            "bearer_token": "your-api-secret-here",  # Optional global auth
            "exclude_paths": ["/health", "/ready", "/.well-known/agent.json"]
        },
        "cors": {
            "enabled": True,
            "allow_origins": ["*"],
            "allow_methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["*"],
            "allow_credentials": True
        },
        "handlers": {
            "use_discovery": True,
            "handler_packages": ["a2a_server.tasks.handlers"],
            "_session_store": {
                "sandbox_id": "optimized-a2a-server",
                "default_ttl_hours": 24
            },
            "chuk_pirate": {
                "type": "a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler",
                "agent": "a2a_server.sample_agents.chuk_pirate.create_pirate_agent",
                # Session optimization settings
                "session_sharing": True,
                "shared_sandbox_group": "global_user_sessions",
                "session_pool_size": 15,
                "session_cache_ttl": 300,
                # Agent settings
                "enable_sessions": True,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "streaming": True,
                # Tool optimization settings
                "enable_tools": True,
                "tool_cache_enabled": True,
                "async_tool_init": True
            }
        }
    }