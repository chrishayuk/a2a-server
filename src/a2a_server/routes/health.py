#!/usr/bin/env python3
# a2a_server/routes/health.py
"""
Light-weight public health-check & liveness endpoints.

Why a dedicated module?
-----------------------
* Keeps the *application factory* clean.
* Lets you expose multiple flavours of “health” that play well with
  Kubernetes / Nomad / Fly.io, etc.

Endpoints
---------
/health
    • Always returns **200** when the process is alive.  
    • Includes a snapshot of registered handlers and (optionally)
      redacted handler-config.

    This is safe to expose publicly; no secret data is leaked.

/ready
    • Returns **200** **only** when at least one task-handler is
      registered **and** the default handler exists.  
    • Use as *readinessProbe* - e.g. fail fast if startup config is bad.

/agent-cards
    • Convenience wrapper around :func:`a2a_server.agent_card.get_agent_cards`
      so load-balancers or front-ends can discover cards without parsing
      the whole OpenAPI schema.

All routes are included in the public schema so ops tooling can see
them; remove ``include_in_schema`` or add an auth-guard if you prefer.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a_server.agent_card import get_agent_cards

logger = logging.getLogger(__name__)

_START_TS = datetime.now(tz=timezone.utc)  # monotonic enough for uptime


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #


def _masked_config(cfg: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """
    Redact obviously-sensitive bits (``api_key``, ``token`` …) before we dump
    config back to a caller.

    Anything that looks risky is replaced with ``"***"``.
    """
    if not cfg:
        return {}

    SENSITIVE = {"api_key", "token", "access_key", "secret", "password"}

    redacted: Dict[str, Dict[str, Any]] = {}
    for handler, params in cfg.items():
        redacted[handler] = {
            k: ("***" if k.lower() in SENSITIVE else v)
            for k, v in params.items()
        }
    return redacted


def _handler_names(task_manager) -> List[str]:
    handlers = task_manager.get_handlers()
    if isinstance(handlers, dict):                 # new task-manager API
        return list(handlers.keys())
    return [h.name for h in handlers]              # legacy list API


# --------------------------------------------------------------------------- #
#  Route registration                                                          #
# --------------------------------------------------------------------------- #


def register_health_routes(  # noqa: D401
    app: FastAPI,
    task_manager,
    handlers_config: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """
    Attach `/health`, `/ready` and `/agent-cards` to *app*.

    The registration is **idempotent**; calling it twice is harmless.
    """

    # ── /health ───────────────────────────────────────────────────────── #
    @app.get("/health", response_class=JSONResponse, tags=["Health"])
    async def health() -> Dict[str, Any]:  # noqa: D401
        """Basic liveness probe - always returns HTTP 200 when process is up."""
        return {
            "status": "ok",
            "service": "A2A Server",
            "uptime_s": round((datetime.now(tz=timezone.utc) - _START_TS).total_seconds()),
            "handlers": _handler_names(task_manager),
            "default_handler": getattr(task_manager.get_default_handler(), "name", None),
            "config": _masked_config(handlers_config),
        }

    # ── /ready ────────────────────────────────────────────────────────── #
    @app.get("/ready", response_class=JSONResponse, tags=["Health"])
    async def ready() -> Dict[str, Any]:  # noqa: D401
        """
        Readiness probe - returns 200 only when the server is really usable
        (at least one handler + a default handler active).
        """
        handlers = _handler_names(task_manager)
        default  = task_manager.get_default_handler()

        if not handlers or default is None:
            # FastAPI will turn the dict into JSON automatically
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "no handlers registered"},
            )

        return {"status": "ready"}

    # ── /agent-cards ──────────────────────────────────────────────────── #
    @app.get("/agent-cards", response_class=JSONResponse, tags=["Health"])
    async def agent_cards(request: Request) -> Dict[str, Any]:  # noqa: D401
        """
        Return the full set of agent-cards (raw JSON) as seen by this node.

        Useful for service-discovery layers that want to surface card data
        without relying on the separate ``/agent-card.json`` path.
        """
        base = str(request.base_url).rstrip("/")
        cards = get_agent_cards(handlers_config or {}, base)
        return {name: card.dict(exclude_none=True) for name, card in cards.items()}

    logger.debug("Health routes registered")
