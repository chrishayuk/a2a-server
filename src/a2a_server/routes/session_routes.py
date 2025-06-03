#!/usr/bin/env python3
# a2a_server/routes/session_routes.py
"""
Private session-inspection helpers.

*   Protected by the shared-secret admin guard (`A2A_ADMIN_TOKEN`)
*   Can be **entirely disabled** at start-up by setting  
    `A2A_DISABLE_SESSION_ROUTES=1`
*   Routes are hidden from the generated OpenAPI schema by default
    (`include_in_schema=False`).

To access, supply the token in the `X-A2A-Admin-Token` header.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

# ── internal imports ────────────────────────────────────────────────────
from a2a_server.tasks.handlers.adk.session_enabled_adk_handler import (
    SessionAwareTaskHandler,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------- #
# Feature-flag & admin guard                                             #
# ---------------------------------------------------------------------- #

_ROUTES_DISABLED_ENV = "A2A_DISABLE_SESSION_ROUTES"
_ADMIN_TOKEN_ENV = "A2A_ADMIN_TOKEN"


def _admin_guard(x_a2a_admin_token: str | None = None) -> None:  # noqa: D401
    """Reject requests when the admin token is missing/incorrect."""
    expected = os.getenv(_ADMIN_TOKEN_ENV)
    if expected and x_a2a_admin_token != expected:
        logger.warning("Blocked unauthorised access to session endpoint")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token required",
        )


# ---------------------------------------------------------------------- #
# Route registration                                                     #
# ---------------------------------------------------------------------- #


def register_session_routes(app: FastAPI) -> None:  # noqa: D401
    """Attach guarded session-management endpoints to *app* (unless disabled)."""
    if os.getenv(_ROUTES_DISABLED_ENV):
        logger.info("Session routes disabled via %s", _ROUTES_DISABLED_ENV)
        return

    guard = Depends(_admin_guard)  # evaluated for every request

    # ── /sessions - list active sessions ─────────────────────────────── #
    @app.get(
        "/sessions",
        tags=["Sessions"],
        summary="List active sessions",
        response_class=JSONResponse,
        dependencies=[guard],
        include_in_schema=False,
    )
    async def list_sessions(request: Request) -> Dict[str, Any]:  # noqa: D401
        task_manager = request.app.state.task_manager
        session_store = request.app.state.session_store

        results: Dict[str, List[Dict[str, str]]] = {}
        for h in task_manager.get_handlers():
            handler = task_manager._handlers[h]
            if isinstance(handler, SessionAwareTaskHandler):
                results[handler.name] = [
                    {
                        "a2a_session_id": a2a_id,
                        "chuk_session_id": chuk_id,
                    }
                    for a2a_id, chuk_id in handler._session_map.items()
                ]

        return {
            "handlers_with_sessions": results,
            "total_sessions_in_store": len(await session_store.list_sessions()),
        }

    # ── /sessions/{id}/history - conversation log ───────────────────── #
    @app.get(
        "/sessions/{session_id}/history",
        tags=["Sessions"],
        summary="Get session history",
        response_class=JSONResponse,
        dependencies=[guard],
        include_in_schema=False,
    )
    async def get_session_history(  # noqa: D401
        session_id: str,
        request: Request,
        handler_name: Optional[str] = Query(
            None, description="Handler name (uses default if not specified)"
        ),
    ) -> Dict[str, Any]:
        task_manager = request.app.state.task_manager

        handler = _resolve_handler(task_manager, handler_name)
        _ensure_session_capable(handler)

        history = await handler.get_conversation_history(session_id)
        return {
            "session_id": session_id,
            "handler": handler.name,
            "messages": history,
        }

    # ── /sessions/{id}/tokens - token usage ─────────────────────────── #
    @app.get(
        "/sessions/{session_id}/tokens",
        tags=["Sessions"],
        summary="Get token usage",
        response_class=JSONResponse,
        dependencies=[guard],
        include_in_schema=False,
    )
    async def get_session_tokens(  # noqa: D401
        session_id: str,
        request: Request,
        handler_name: Optional[str] = Query(
            None, description="Handler name (uses default if not specified)"
        ),
    ) -> Dict[str, Any]:
        task_manager = request.app.state.task_manager

        handler = _resolve_handler(task_manager, handler_name)
        _ensure_session_capable(handler)

        token_usage = await handler.get_token_usage(session_id)
        return {
            "session_id": session_id,
            "handler": handler.name,
            "token_usage": token_usage,
        }

    logger.debug("Session routes registered")


# ---------------------------------------------------------------------- #
# Helpers                                                                #
# ---------------------------------------------------------------------- #


def _resolve_handler(task_manager, name: Optional[str]):
    """Return the requested handler or the default one."""
    if name:
        if name not in task_manager.get_handlers():
            raise HTTPException(status_code=404, detail=f"Handler {name} not found")
        return task_manager._handlers[name]

    default_name = task_manager.get_default_handler()
    if not default_name:
        raise HTTPException(status_code=404, detail="No default handler configured")
    return task_manager._handlers[default_name]


def _ensure_session_capable(handler) -> None:
    """Guard that *handler* supports conversations / token-usage APIs."""
    if not isinstance(handler, SessionAwareTaskHandler):
        raise HTTPException(
            status_code=400,
            detail=f"Handler {handler.name} does not support sessions",
        )
