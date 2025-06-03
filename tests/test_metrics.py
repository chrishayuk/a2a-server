# File: tests/test_metrics.py
"""
Unit-tests for the metrics helper.

*   Ensures that the Console exporter is invoked when no OTLP endpoint
    is configured.
*   Verifies that calling `instrument_app()` twice is a no-op
    (middleware not duplicated, flag set).
"""
import asyncio
import inspect
import json
import logging
import uuid
import os
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse

from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_json_rpc.spec import (
    JSONRPCRequest,
    TaskArtifactUpdateEvent,
    TaskSendParams,
    TaskState,
    TaskStatusUpdateEvent,
)
from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_manager import Task, TaskManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables - override via env vars if needed
# ---------------------------------------------------------------------------

MAX_BODY = int(os.getenv("MAX_JSONRPC_BODY", 2 * 1024 * 1024))  # 2 MiB
REQUEST_TIMEOUT = float(os.getenv("JSONRPC_TIMEOUT", 15.0))      # seconds
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_terminal(state: TaskState) -> bool:
    return state in {TaskState.completed, TaskState.canceled, TaskState.failed}


async def _create_task(
    tm: TaskManager, params: TaskSendParams, handler: str | None
) -> Tuple[Task, str, str]:
    """Copes with both *new* and *legacy* TaskManager signatures."""
    client_id = params.id
    original = inspect.unwrap(tm.create_task)
    bound: Callable[..., Awaitable[Task]] = original.__get__(tm, tm.__class__)  # type: ignore[assignment]
    sig = inspect.signature(original)

    if "task_id" in sig.parameters:  # new‑style
        task = await bound(
            params.message, session_id=params.session_id, handler_name=handler, task_id=client_id
        )
        return task, task.id, task.id

    # legacy
    task = await bound(params.message, session_id=params.session_id, handler_name=handler)
    server_id = task.id
    if client_id and client_id != server_id:
        async with tm._lock:  # noqa: SLF001
            tm._aliases[client_id] = server_id  # type: ignore[attr-defined]
    else:
        client_id = server_id
    return task, server_id, client_id

# ---------------------------------------------------------------------------
# SSE implementation for tasks/sendSubscribe
# ---------------------------------------------------------------------------
async def _stream_send_subscribe(
    payload: JSONRPCRequest,
    tm: TaskManager,
    bus: EventBus,
    handler_name: str | None,
) -> StreamingResponse:
    raw = dict(payload.params)
    if handler_name:
        raw["handler"] = handler_name
    params = TaskSendParams.model_validate(raw)

    try:
        task, server_id, client_id = await _create_task(tm, params, handler_name)
    except ValueError as exc:
        if "already exists" in str(exc).lower():
            task = await tm.get_task(params.id)  # type: ignore[arg-type]
            server_id, client_id = task.id, params.id
        else:
            raise

    logger.info(
        "[transport.http] created task server_id=%s client_id=%s handler=%s",
        server_id,
        client_id,
        handler_name or "<default>",
    )

    queue = bus.subscribe()

    async def _event_source():
        try:
            while True:
                event = await queue.get()
                if getattr(event, "id", None) != server_id:
                    continue

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
                    jsonrpc="2.0", id=payload.id, method="tasks/event", params=body
                )
                yield f"data: {notif.model_dump_json()}\n\n"

                if getattr(event, "final", False) or (
                    isinstance(event, TaskStatusUpdateEvent) and _is_terminal(event.status.state)
                ):
                    break
        except asyncio.CancelledError:
            logger.debug("SSE client for %s disconnected", client_id)
            raise
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        _event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )

# ---------------------------------------------------------------------------
# Mount routes
# ---------------------------------------------------------------------------

def setup_http(
    app: FastAPI,
    protocol: JSONRPCProtocol,
    task_manager: TaskManager,
    event_bus: Optional[EventBus] = None,
) -> None:
    """Mount default + per‑handler JSON‑RPC endpoints on *app*."""

    # ---- global middleware: body‑size guard --------------------------------
    @app.middleware("http")
    async def _limit_body(request: Request, call_next):  # noqa: D401, ANN001
        if int(request.headers.get("content-length", 0)) > MAX_BODY:
            raise HTTPException(413, "Payload too large")
        return await call_next(request)

    # ---- helpers -----------------------------------------------------------
    async def _dispatch(req: JSONRPCRequest) -> Response:
        if not isinstance(req.params, dict):
            raise HTTPException(422, "params must be an object")

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                raw = await protocol._handle_raw_async(req.model_dump())
        except TimeoutError:
            raise HTTPException(504, "Handler timed‑out") from None

        return Response(status_code=204) if raw is None else JSONResponse(jsonable_encoder(raw))

    # ---- /rpc  -------------------------------------------------------------
    @app.post("/rpc")
    async def _default_rpc(payload: JSONRPCRequest = Body(...)):  # noqa: D401
        if payload.method == "tasks/send":
            payload.params["id"] = str(uuid.uuid4())
        return await _dispatch(payload)

    # ---- one sub‑tree per handler -----------------------------------------
    for handler in task_manager.get_handlers():

        @app.post(f"/{handler}/rpc")  # type: ignore[misc]
        async def _handler_rpc(payload: JSONRPCRequest = Body(...), _h: str = handler):  # noqa: D401
            if payload.method == "tasks/send":
                payload.params["id"] = str(uuid.uuid4())
            if payload.method in {"tasks/send", "tasks/sendSubscribe"}:
                payload.params.setdefault("handler", _h)
            return await _dispatch(payload)

        if event_bus:

            @app.post(f"/{handler}")  # type: ignore[misc]
            async def _handler_alias(payload: JSONRPCRequest = Body(...), _h: str = handler):  # noqa: D401
                if payload.method == "tasks/send":
                    payload.params["id"] = str(uuid.uuid4())

                if payload.method == "tasks/sendSubscribe":
                    return await _stream_send_subscribe(payload, task_manager, event_bus, _h)

                payload.params.setdefault("handler", _h)
                return await _dispatch(payload)

        logger.debug("[transport.http] routes registered for handler %s", handler)

__all__ = ["setup_http"]
