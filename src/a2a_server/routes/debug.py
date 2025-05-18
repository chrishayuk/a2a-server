# a2a_server/routes/debug.py
from __future__ import annotations
"""
Private debug endpoints for the A2A server.

* All routes are protected by a very lightweight shared-secret guard.
* Set an ``A2A_ADMIN_TOKEN`` environment variable, then include the same
  value in every request header:  ``X-A2A-Admin-Token: <token>``.
* If the env-var is **unset**, the guard falls through (handy in local dev).

These routes are excluded from the OpenAPI schema on purpose.
"""

import logging
import os
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Admin-token guard                                                          #
# --------------------------------------------------------------------------- #

_ENV_VAR = "A2A_ADMIN_TOKEN"
_HEADER  = "X-A2A-Admin-Token"


def _admin_guard(  # noqa: D401
    token: str | None = Header(None, alias=_HEADER),
) -> None:
    """
    Shared-secret check.

    * If ``A2A_ADMIN_TOKEN`` is defined ↠ header **must** be present **and**
      match, otherwise we raise *401 Unauthorised*.
    * If the env-var is missing ↠ guard is disabled (local dev convenience).
    """
    expected = os.getenv(_ENV_VAR)
    if expected and token != expected:
        logger.warning("Blocked unauthorised access to debug endpoint")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token required",
        )


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #


def _handler_names(handlers: Any) -> List[str]:
    """
    Convert whatever ``TaskManager.get_handlers()`` returns into a list
    of handler names, without assuming its exact type.
    """
    if isinstance(handlers, dict):
        return list(handlers.keys())
    return [h.name if hasattr(h, "name") else str(h) for h in handlers]


def _default_handler_name(task_manager) -> str | None:
    default = task_manager.get_default_handler()
    if hasattr(default, "name"):          # handler object
        return default.name
    return default                        # already a str or None


# --------------------------------------------------------------------------- #
#  Route registration                                                          #
# --------------------------------------------------------------------------- #


def register_debug_routes(app: FastAPI, event_bus, task_manager) -> None:  # noqa: D401
    """
    Mount the *private* debug routes onto *app*.

    They all depend on :func:`_admin_guard` so only trusted callers with the
    shared token can see them.
    """

    guard_dep = Depends(_admin_guard)

    # ── event-bus snapshot ────────────────────────────────────────────── #
    @app.get(
        "/debug/event-bus",
        dependencies=[guard_dep],
        response_class=JSONResponse,
        include_in_schema=False,
    )
    async def debug_event_bus() -> Dict[str, Any]:  # noqa: D401
        """Return a quick overview of subscriptions & registered handlers."""
        return {
            "status": "ok",
            "subscriptions": len(event_bus._queues),
            "handlers": _handler_names(task_manager.get_handlers()),
            "default_handler": _default_handler_name(task_manager),
        }

    # ── synthetic status-event injector ───────────────────────────────── #
    @app.post(
        "/debug/test-event/{task_id}",
        dependencies=[guard_dep],
        response_class=JSONResponse,
        include_in_schema=False,
    )
    async def debug_test_event(  # noqa: D401
        task_id: str,
        message: str = "Test message",
    ) -> Dict[str, str]:
        """
        Publish a *completed* status update for *task_id* carrying *message*.
        Useful for front-end / client polling tests.
        """
        # Lazy import keeps prod cold-start minimal
        from a2a_json_rpc.spec import (
            Message,
            Role,
            TaskState,
            TaskStatus,
            TaskStatusUpdateEvent,
            TextPart,
        )

        text_part = TextPart(type="text", text=message)
        completed_msg = Message(role=Role.agent, parts=[text_part])

        status_obj = TaskStatus(state=TaskState.completed)
        # pydantic dataclass: assign extra field via object.__setattr__
        object.__setattr__(status_obj, "message", completed_msg)

        await event_bus.publish(
            TaskStatusUpdateEvent(id=task_id, status=status_obj, final=True)
        )

        return {"status": "ok", "message": "Test event published"}
