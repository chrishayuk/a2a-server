# File: a2a/server/transport/http.py
"""
a2a.server.transport.http
================================
HTTP JSON-RPC transport layer with first-class streaming (SSE) support.
"""
from __future__ import annotations

import inspect
import json
import logging
import uuid
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, HTTPException, Body
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse

# a2a imports
from a2a.json_rpc.spec import JSONRPCRequest
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.json_rpc.spec import (
    TaskArtifactUpdateEvent,
    TaskSendParams,
    TaskStatusUpdateEvent,
    TaskState,
)
from a2a.server.pubsub import EventBus
from a2a.server.tasks.task_manager import TaskManager, Task

logger = logging.getLogger(__name__)


def _is_terminal(state: TaskState) -> bool:
    return state in (TaskState.completed, TaskState.canceled, TaskState.failed)


async def _create_task(
    tm: TaskManager,
    params: TaskSendParams,
    handler: Optional[str],
) -> Tuple[Task, str, str]:
    client_id = params.id
    original = inspect.unwrap(tm.create_task)
    bound = original.__get__(tm, tm.__class__)
    sig = inspect.signature(original)

    # If TM supports explicit task_id injection:
    if "task_id" in sig.parameters:
        task = await bound(
            params.message,
            session_id=params.session_id,
            handler_name=handler,
            task_id=client_id,
        )
        return task, task.id, task.id

    # Legacy: server generates its own ID, then alias
    task = await bound(
        params.message,
        session_id=params.session_id,
        handler_name=handler,
    )
    server_id = task.id
    if client_id and client_id != server_id:
        async with tm._lock:
            tm._aliases[client_id] = server_id
    else:
        client_id = server_id
    return task, server_id, client_id


async def _streaming_send_subscribe(
    payload: JSONRPCRequest,
    tm: TaskManager,
    bus: EventBus,
    handler_name: Optional[str],
) -> StreamingResponse:
    raw = dict(payload.params)
    if handler_name:
        raw["handler"] = handler_name
    params = TaskSendParams.model_validate(raw)

    try:
        task, server_id, client_id = await _create_task(tm, params, handler_name)
    except ValueError as e:
        msg = str(e).lower()
        if "already exists" in msg:
            server_id = params.id
            client_id = params.id
        else:
            raise

    logger.info(
        "[transport.http] created task server_id=%s client_id=%s handler=%s",
        server_id, client_id, handler_name or "<default>"
    )

    queue = bus.subscribe()

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if getattr(event, "id", None) != server_id:
                    continue

                # Serialize via Pydantic model_dump
                if isinstance(event, TaskStatusUpdateEvent):
                    params_dict = event.model_dump(exclude_none=True)
                    params_dict["id"] = client_id
                    params_dict["type"] = "status"
                elif isinstance(event, TaskArtifactUpdateEvent):
                    params_dict = event.model_dump(exclude_none=True)
                    params_dict["id"] = client_id
                    params_dict["type"] = "artifact"
                else:
                    params_dict = event.model_dump(exclude_none=True)
                    params_dict["id"] = client_id

                # Wrap in JSONRPCRequest spec
                notification = JSONRPCRequest(
                    jsonrpc="2.0",
                    id=payload.id,
                    method="tasks/event",
                    params=params_dict,
                )

                # chunk
                chunk = notification.model_dump_json()
                yield f"data: {chunk}\n\n"

                # stop on terminal
                if getattr(event, "final", False) or (
                    isinstance(event, TaskStatusUpdateEvent) and _is_terminal(
                        event.status.state
                    )
                ):
                    break
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def setup_http(
    app: FastAPI,
    protocol: JSONRPCProtocol,
    task_manager: TaskManager,
    event_bus: EventBus | None = None,
) -> None:
    @app.post("/rpc")
    async def default_rpc(payload: JSONRPCRequest = Body(...)):
        # assign a fresh alias for each send
        if payload.method == "tasks/send":
            payload.params["id"] = str(uuid.uuid4())
        raw = await protocol._handle_raw_async(payload.model_dump())
        return Response(status_code=204) if raw is None else JSONResponse(
            jsonable_encoder(raw)
        )

    for handler in task_manager.get_handlers():
        @app.post(f"/{handler}/rpc")  # type: ignore
        async def handler_rpc(payload: JSONRPCRequest = Body(...), _h=handler):
            if payload.method == "tasks/send":
                payload.params["id"] = str(uuid.uuid4())
            if payload.method in ("tasks/send", "tasks/sendSubscribe"):
                payload.params.setdefault("handler", _h)
            raw = await protocol._handle_raw_async(payload.model_dump())
            return Response(status_code=204) if raw is None else JSONResponse(
                jsonable_encoder(raw)
            )

        if event_bus:
            @app.post(f"/{handler}")  # type: ignore
            async def handler_alias(payload: JSONRPCRequest = Body(...), _h=handler):
                if payload.method == "tasks/send":
                    payload.params["id"] = str(uuid.uuid4())
                if payload.method == "tasks/sendSubscribe":
                    try:
                        return await _streaming_send_subscribe(
                            payload, task_manager, event_bus, _h
                        )
                    except Exception as exc:
                        logger.error("[transport.http] streaming failed", exc_info=True)
                        raise HTTPException(status_code=500, detail=str(exc)) from exc
                payload.params.setdefault("handler", _h)
                raw = await protocol._handle_raw_async(payload.model_dump())
                return Response(status_code=204) if raw is None else JSONResponse(
                    jsonable_encoder(raw)
                )

        logger.debug("[transport.http] routes registered for handler %s", handler)


__all__ = ["setup_http"]
