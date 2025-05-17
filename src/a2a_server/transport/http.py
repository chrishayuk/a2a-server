# a2a_server/transport/http.py
"""
a2a_server.transport.http
=========================
HTTP JSON-RPC transport layer with first-class SSE streaming support.
"""
from __future__ import annotations

import inspect
import json
import logging
import uuid
from typing import Any, Dict, Optional, Tuple, Callable, Awaitable

from fastapi import FastAPI, Body, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse

from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_json_rpc.spec import (
    JSONRPCRequest,
    TaskSendParams,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)
from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_manager import TaskManager, Task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------


def _is_terminal(state: TaskState) -> bool:
    """True when *state* is one of the terminal task states."""
    return state in (TaskState.completed, TaskState.canceled, TaskState.failed)


async def _create_task(
    tm: TaskManager,
    params: TaskSendParams,
    handler: str | None,
) -> Tuple[Task, str, str]:
    """
    Helper that copes with both “new” and “legacy” TaskManager signatures.

    Returns ``(task, real_id, client_id)`` - where *real_id* is whatever the
    TaskManager ultimately assigned and *client_id* is the alias we’ll use on
    the wire.
    """
    client_id = params.id
    original = inspect.unwrap(tm.create_task)
    bound: Callable[..., Awaitable[Task]] = original.__get__(tm, tm.__class__)  # type: ignore[assignment]
    sig = inspect.signature(original)

    # New-style: TaskManager lets us inject *task_id* up-front
    if "task_id" in sig.parameters:
        task = await bound(
            params.message,
            session_id=params.session_id,
            handler_name=handler,
            task_id=client_id,
        )
        return task, task.id, task.id

    # Old-style: create, then optionally add an alias
    task = await bound(
        params.message,
        session_id=params.session_id,
        handler_name=handler,
    )
    server_id = task.id
    if client_id and client_id != server_id:
        async with tm._lock:  # noqa: SLF001 - internal but harmless here
            tm._aliases[client_id] = server_id  # type: ignore[attr-defined]
    else:
        client_id = server_id
    return task, server_id, client_id


# ---------------------------------------------------------------------------


async def _stream_send_subscribe(
    payload: JSONRPCRequest,
    tm: TaskManager,
    bus: EventBus,
    handler_name: str | None,
) -> StreamingResponse:
    """
    Implements the ``tasks/sendSubscribe`` “SSE subscription right-away” call.

    We create (or reuse) the task, then stream *all* events for that task down
    an SSE connection encoded as JSON-RPC notifications.
    """
    raw = dict(payload.params)
    if handler_name:
        raw["handler"] = handler_name
    params = TaskSendParams.model_validate(raw)

    # ── Create task … or reuse existing one ────────────────────────────
    try:
        task, server_id, client_id = await _create_task(tm, params, handler_name)
    except ValueError as exc:
        if "already exists" in str(exc).lower():
            task = await tm.get_task(params.id)  # type: ignore[arg-type]
            server_id = task.id
            client_id = params.id
        else:
            raise

    logger.info(
        "[transport.http] created task server_id=%s client_id=%s handler=%s",
        server_id,
        client_id,
        handler_name or "<default>",
    )

    # ── Stream events ──────────────────────────────────────────────────
    queue = bus.subscribe()

    async def _event_source():
        try:
            while True:
                event = await queue.get()
                if getattr(event, "id", None) != server_id:
                    continue

                # --- serialise the event ---------------------------------
                if isinstance(event, TaskStatusUpdateEvent):
                    body = event.model_dump(exclude_none=True)
                    body.update(id=client_id, type="status")
                elif isinstance(event, TaskArtifactUpdateEvent):
                    body = event.model_dump(exclude_none=True)
                    body.update(id=client_id, type="artifact")
                else:
                    body = event.model_dump(exclude_none=True)
                    body["id"] = client_id

                notif = JSONRPCRequest(
                    jsonrpc="2.0",
                    id=payload.id,
                    method="tasks/event",
                    params=body,
                )

                yield f"data: {notif.model_dump_json()}\n\n"

                # stop once the task is done
                final = getattr(event, "final", False)
                if final or (
                    isinstance(event, TaskStatusUpdateEvent)
                    and _is_terminal(event.status.state)
                ):
                    break
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        _event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Public setup helper
# ---------------------------------------------------------------------------

def setup_http(
    app: FastAPI,
    protocol: JSONRPCProtocol,
    task_manager: TaskManager,
    event_bus: EventBus | None = None,
) -> None:
    """Mount *all* HTTP routes (default + per-handler variations) on *app*."""

    # ── /rpc  ──────────────────────────────────────────────────────────
    @app.post("/rpc")
    async def _default_rpc(payload: JSONRPCRequest = Body(...)):  # noqa: D401
        if payload.method == "tasks/send":  # force fresh client-side alias
            payload.params["id"] = str(uuid.uuid4())
        raw = await protocol._handle_raw_async(payload.model_dump())
        return (
            Response(status_code=204)
            if raw is None
            else JSONResponse(jsonable_encoder(raw))
        )

    # ──  one sub-tree per registered handler  ─────────────────────────
    for handler in task_manager.get_handlers():

        @app.post(f"/{handler}/rpc")  # type: ignore[misc]
        async def _handler_rpc(
            payload: JSONRPCRequest = Body(...),
            _h: str = handler,
        ):  # noqa: D401
            if payload.method == "tasks/send":
                payload.params["id"] = str(uuid.uuid4())
            if payload.method in {"tasks/send", "tasks/sendSubscribe"}:
                payload.params.setdefault("handler", _h)
            raw = await protocol._handle_raw_async(payload.model_dump())
            return (
                Response(status_code=204)
                if raw is None
                else JSONResponse(jsonable_encoder(raw))
            )

        if event_bus:

            @app.post(f"/{handler}")  # type: ignore[misc]
            async def _handler_alias(
                payload: JSONRPCRequest = Body(...),
                _h: str = handler,
            ):  # noqa: D401
                if payload.method == "tasks/send":
                    payload.params["id"] = str(uuid.uuid4())

                if payload.method == "tasks/sendSubscribe":
                    try:
                        return await _stream_send_subscribe(
                            payload, task_manager, event_bus, _h
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.error("streaming failed", exc_info=True)
                        raise HTTPException(status_code=500, detail=str(exc)) from exc

                payload.params.setdefault("handler", _h)
                raw = await protocol._handle_raw_async(payload.model_dump())
                return (
                    Response(status_code=204)
                    if raw is None
                    else JSONResponse(jsonable_encoder(raw))
                )

        logger.debug("[transport.http] routes registered for handler %s", handler)


__all__ = ["setup_http"]
