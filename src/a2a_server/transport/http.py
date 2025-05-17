# a2a_server/transport/http.py
from __future__ import annotations
"""
HTTP JSON-RPC transport layer (async-native)
===========================================
Drop-in replacement for **a2a_server.transport.http** that eliminates the last
synchronous choke-points:

* **Streaming body-size guard** - abort uploads as soon as they exceed
  ``MAX_JSONRPC_BODY`` (even when *Content-Length* is absent).
* **Off-thread JSON serialisation** for chatty SSE streams.
* **Same public routes/behaviour** - no change to FastAPI schemas or clients.

May-2025
"""
import asyncio
import inspect
import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
# Tunables (override with env vars)
# ---------------------------------------------------------------------------
MAX_BODY: int = int(os.getenv("MAX_JSONRPC_BODY", 2 * 1024 * 1024))  # 2 MiB
REQUEST_TIMEOUT: float = float(os.getenv("JSONRPC_TIMEOUT", 15.0))    # seconds

# ---------------------------------------------------------------------------
# Middleware: streaming body‑size limiter
# ---------------------------------------------------------------------------


class BodySizeLimiterMiddleware(BaseHTTPMiddleware):
    """Abort requests whose bodies exceed *max_body* bytes.

    * If *Content‑Length* is present and already over the threshold we fail
      **immediately** (no body read, cheap fast‑path).
    * Otherwise we wrap the ASGI *receive* channel and count bytes chunk by
      chunk, raising once the cumulative total crosses the limit.
    """

    def __init__(self, app, max_body: int) -> None:  # noqa: D401
        super().__init__(app)
        self.max_body = max_body

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Fast‑path: respect declared Content‑Length --------------------------------
        try:
            clen = int(request.headers.get("content-length", 0))
        except ValueError:
            clen = 0
        if clen > self.max_body:
            return JSONResponse({"detail": "Payload too large"}, status_code=413)

        # Slow‑path: stream & count --------------------------------------------------
        total = 0
        original_receive = request._receive  # type: ignore[attr-defined]

        async def _limited_receive():
            nonlocal total
            message = await original_receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_body:
                    raise HTTPException(status_code=413, detail="Payload too large")
            return message

        request._receive = _limited_receive  # type: ignore[attr-defined]
        try:
            return await call_next(request)
        finally:
            request._receive = original_receive  # type: ignore[attr-defined]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


aasync = None  # silence legacy linters complaining about the historical typo


def _is_terminal(state: TaskState) -> bool:
    return state in {TaskState.completed, TaskState.canceled, TaskState.failed}


async def _create_task(
    tm: TaskManager,
    params: TaskSendParams,
    handler: str | None,
) -> Tuple[Task, str, str]:
    """Helper that works with both *new* and *legacy* ``TaskManager`` signatures."""

    client_id = params.id
    original = inspect.unwrap(tm.create_task)
    bound: Callable[..., Awaitable[Task]] = original.__get__(tm, tm.__class__)  # type: ignore[assignment]
    sig = inspect.signature(original)

    # New‑style API - TaskManager accepts ``task_id``
    if "task_id" in sig.parameters:
        task = await bound(
            params.message,
            session_id=params.session_id,
            handler_name=handler,
            task_id=client_id,
        )
        return task, task.id, task.id

    # Legacy - create then alias
    task = await bound(params.message, session_id=params.session_id, handler_name=handler)
    server_id = task.id
    if client_id and client_id != server_id:
        async with tm._lock:  # noqa: SLF001 - harmless here
            tm._aliases[client_id] = server_id  # type: ignore[attr-defined]
    else:
        client_id = server_id
    return task, server_id, client_id


# ---------------------------------------------------------------------------
# SSE implementation - tasks/sendSubscribe
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

                # serialisation ---------------------------------------------
                if isinstance(event, TaskStatusUpdateEvent):
                    body = event.model_dump(exclude_none=True)
                    body.update(id=client_id, type="status")
                elif isinstance(event, TaskArtifactUpdateEvent):
                    body = event.model_dump(exclude_none=True)
                    body.update(id=client_id, type="artifact")
                else:
                    body = event.model_dump(exclude_none=True)
                    body["id"] = client_id

                # Off‑thread JSON serialisation (CPU‑bound when streams are busy)
                wire_dict = JSONRPCRequest(
                    jsonrpc="2.0", id=payload.id, method="tasks/event", params=body
                ).model_dump(mode="json")
                data = await asyncio.to_thread(json.dumps, wire_dict, separators=(",", ":"))

                yield f"data: {data}\n\n"

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
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Route‑mount helper (public)
# ---------------------------------------------------------------------------


def setup_http(
    app: FastAPI,
    protocol: JSONRPCProtocol,
    task_manager: TaskManager,
    event_bus: Optional[EventBus] = None,
) -> None:
    """Mount default + per‑handler JSON‑RPC endpoints on *app*."""

    # ---- global middleware (size guard) ----------------------------------
    app.add_middleware(BodySizeLimiterMiddleware, max_body=MAX_BODY)

    # ---- helper: run through Protocol with timeout & param validation -----

    async def _dispatch(req: JSONRPCRequest) -> Response:
        if not isinstance(req.params, dict):
            return JSONResponse({"detail": "params must be an object"}, status_code=422)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                raw = await protocol._handle_raw_async(req.model_dump())
        except TimeoutError:
            return JSONResponse({"detail": "Handler timed-out"}, status_code=504)

        return Response(status_code=204) if raw is None else JSONResponse(jsonable_encoder(raw))

    # ---- /rpc  (default handler) -----------------------------------------

    @app.post("/rpc")
    async def _default_rpc(payload: JSONRPCRequest = Body(...)):  # noqa: D401
        if payload.method == "tasks/send" and isinstance(payload.params, dict):
            payload.params["id"] = str(uuid.uuid4())
        return await _dispatch(payload)

    # ---- per‑handler sub‑trees  ------------------------------------------

    for handler in task_manager.get_handlers():

        @app.post(f"/{handler}/rpc")  # type: ignore[misc]
        async def _handler_rpc(
            payload: JSONRPCRequest = Body(...),
            _h: str = handler,
        ):  # noqa: D401
            if payload.method == "tasks/send" and isinstance(payload.params, dict):
                payload.params["id"] = str(uuid.uuid4())
            if payload.method in {"tasks/send", "tasks/sendSubscribe"} and isinstance(payload.params, dict):
                payload.params.setdefault("handler", _h)
            return await _dispatch(payload)

        if event_bus:

            @app.post(f"/{handler}")  # type: ignore[misc]
            async def _handler_alias(
                payload: JSONRPCRequest = Body(...),
                _h: str = handler,
            ):  # noqa: D401
                if payload.method == "tasks/send" and isinstance(payload.params, dict):
                    payload.params["id"] = str(uuid.uuid4())

                if payload.method == "tasks/sendSubscribe":
                    return await _stream_send_subscribe(payload, task_manager, event_bus, _h)

                if isinstance(payload.params, dict):
                    payload.params.setdefault("handler", _h)
                return await _dispatch(payload)

        logger.debug("[transport.http] routes registered for handler %s", handler)


__all__ = ["setup_http", "MAX_BODY", "REQUEST_TIMEOUT"]
