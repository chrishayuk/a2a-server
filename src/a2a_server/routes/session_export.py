#!/usr/bin/env python3
# a2a_server/routes/session_export.py
"""
Session import / export utilities for the A2A server.

Routes (all require “internal-admin” header)
-------------------------------------------
GET    /sessions                       - list all known session-IDs
GET    /sessions/{session_id}/export   - download a conversation (JSON)
POST   /sessions/import                - bulk-import conversation history
DELETE /sessions/{session_id}          - purge a session from the backing store
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import (
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Guard helpers
# ─────────────────────────────────────────────────────────────────────────────

_ADMIN_HEADER = "X-Internal-Admin"
_EXPECTED_SECRET = os.getenv("A2A_ADMIN_SECRET")  # optional


async def _admin_guard(
    internal_header: str | None = Header(None, alias=_ADMIN_HEADER),
):
    """
    Very small auth-guard.

    * Header **must** be present.
    * If `A2A_ADMIN_SECRET` env-var is set, the header value must match.
    """
    if internal_header is None:
        raise HTTPException(status_code=403, detail=f"Missing {_ADMIN_HEADER} header")

    if _EXPECTED_SECRET and internal_header != _EXPECTED_SECRET:
        raise HTTPException(status_code=403, detail="Bad admin secret")


# ─────────────────────────────────────────────────────────────────────────────
# Capability helpers
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_handler(request: Request, handler_name: str | None):
    """Return the TaskHandler instance (or raise 404)."""
    manager = request.app.state.task_manager
    if handler_name:
        if handler_name not in manager.get_handlers():
            raise HTTPException(status_code=404, detail=f"Handler {handler_name} not found")
        return manager._handlers[handler_name]

    default_name = manager.get_default_handler()
    if not default_name:
        raise HTTPException(status_code=404, detail="No default handler configured")
    return manager._handlers[default_name]


def _check_capability(handler, attr: str, verb: str):
    """Ensure *handler* exposes *attr* (callable)."""
    if not hasattr(handler, attr) or not callable(getattr(handler, attr)):
        raise HTTPException(
            status_code=400,
            detail=f"Handler {handler.name!s} does not support '{verb}'",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Route registration
# ─────────────────────────────────────────────────────────────────────────────


def register_session_routes(app: FastAPI) -> None:
    """
    Attach the guarded session routes to *app*.

    Set the env-var `DISABLE_SESSION_ROUTES=1` to skip registration.
    """
    if os.getenv("DISABLE_SESSION_ROUTES") in {"1", "true", "yes"}:
        logger.info("Session routes are disabled via DISABLE_SESSION_ROUTES")
        return

    route_dep = [Depends(_admin_guard)]  # shared dependency list

    # ── LIST ────────────────────────────────────────────────────────────
    @app.get(
        "/sessions",
        tags=["Sessions"],
        summary="List all known sessions",
        dependencies=route_dep,
    )
    async def list_sessions(
        request: Request,
        handler_name: str | None = None,
        with_details: bool = False,
    ):
        handler = _resolve_handler(request, handler_name)
        _check_capability(handler, "list_sessions", "list_sessions")

        try:
            sessions: list[dict[str, Any]] | list[str] = await handler.list_sessions(
                detail=with_details
            )
        except TypeError:
            sessions = await handler.list_sessions()  # type: ignore

        return {"handler": handler.name, "sessions": sessions}

    # ── EXPORT ──────────────────────────────────────────────────────────
    @app.get(
        "/sessions/{session_id}/export",
        tags=["Sessions"],
        summary="Export a session (download as JSON)",
        dependencies=route_dep,
    )
    async def export_session(
        session_id: str,
        request: Request,
        handler_name: str | None = None,
        include_token_usage: bool = True,
    ):
        handler = _resolve_handler(request, handler_name)
        _check_capability(handler, "get_conversation_history", "session export")

        try:
            history = await handler.get_conversation_history(session_id)
            export_data: Dict[str, Any] = {
                "session_id": session_id,
                "handler": handler.name,
                "conversation": history,
                "exported_at": datetime.utcnow().isoformat(),
            }

            if include_token_usage and hasattr(handler, "get_token_usage"):
                try:
                    export_data["token_usage"] = await handler.get_token_usage(session_id)  # type: ignore
                except Exception as exc:  # pragma: no cover
                    logger.warning("Token-usage lookup failed for %s: %s", session_id, exc)

            filename = f"session_{session_id}_{handler.name}.json"
            return Response(
                content=json.dumps(export_data, indent=2),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error exporting session %s: %s", session_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ── IMPORT ──────────────────────────────────────────────────────────
    @app.post(
        "/sessions/import",
        tags=["Sessions"],
        summary="Import a session",
        dependencies=route_dep,
    )
    async def import_session(
        request: Request,
        session_data: Dict[str, Any] = Body(..., examples={"minimal": {"conversation": []}}),
        handler_name: str | None = None,
    ):
        if not session_data.get("conversation"):
            raise HTTPException(status_code=400, detail="Invalid payload: missing 'conversation' list")

        handler = _resolve_handler(request, handler_name or session_data.get("handler"))
        _check_capability(handler, "add_to_session", "session import")

        new_session_id = str(uuid.uuid4())
        agent_session_id = handler._get_agent_session_id(new_session_id)  # type: ignore[attr-defined]
        if not agent_session_id:
            raise HTTPException(status_code=500, detail="Failed to create handler session")

        imported = 0
        for msg in session_data["conversation"]:
            role = (msg.get("role") or "").lower()
            content = msg.get("content", "")
            if not content:
                continue
            is_agent = role in {"assistant", "system", "ai", "agent"}
            ok = await handler.add_to_session(agent_session_id, content, is_agent=is_agent)  # type: ignore[attr-defined]
            imported += int(bool(ok))

        if not imported:
            raise HTTPException(status_code=400, detail="No messages imported")

        return JSONResponse(
            {
                "status": "success",
                "new_session_id": new_session_id,
                "handler": handler.name,
                "imported_messages": imported,
            }
        )

    # ── DELETE ──────────────────────────────────────────────────────────
    @app.delete(
        "/sessions/{session_id}",
        tags=["Sessions"],
        summary="Delete / purge a session",
        dependencies=route_dep,
    )
    async def delete_session(
        session_id: str,
        request: Request,
        handler_name: str | None = None,
    ):
        handler = _resolve_handler(request, handler_name)
        _check_capability(handler, "delete_session", "delete_session")

        try:
            removed = await handler.delete_session(session_id)
            if not removed:
                raise HTTPException(status_code=404, detail="Session not found or already deleted")
            return {"status": "success", "session_id": session_id}
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover
            logger.exception("Error deleting session %s: %s", session_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Backwards-compat alias (keep old import path working) ────────────────────
def register_session_export_routes(app: FastAPI) -> None:  # noqa: D401
    register_session_routes(app)
