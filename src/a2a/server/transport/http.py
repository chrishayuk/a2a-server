"""a2a.server.transport.http
================================
HTTP JSON‑RPC transport layer with first‑class streaming (SSE) support.

Design goals
------------
* No global monkey‑patching.
* Works seamlessly with the canonical TaskManager (supports `task_id=`).
* Echoes client‑supplied IDs in SSE events.
* Emits both status and artifact events correctly (as separate messages).
* API surface identical to previous `setup_http` so imports remain unchanged.
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse

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
    # Unwrap through any tracing decorators
    original = inspect.unwrap(tm.create_task)
    bound = original.__get__(tm, tm.__class__)
    sig = inspect.signature(original)

    if "task_id" in sig.parameters:
        task = await bound(
            params.message,
            session_id=params.session_id,
            handler_name=handler,
            task_id=client_id,
        )
        return task, task.id, task.id

    # Legacy path: server generates ID, then alias
    task = await bound(
        params.message,
        session_id=params.session_id,
        handler_name=handler,
    )
    server_id = task.id
    if client_id and client_id != server_id:
        async with tm._lock:  # type: ignore[protected-access]
            tm._aliases[client_id] = server_id  # type: ignore[protected-access]
    else:
        client_id = server_id
    return task, server_id, client_id


async def _streaming_send_subscribe(
    payload: Dict[str, Any],
    tm: TaskManager,
    bus: EventBus,
    handler_name: Optional[str],
) -> StreamingResponse:
    raw = dict(payload.get("params") or {})
    if handler_name:
        raw["handler"] = handler_name
    params = TaskSendParams.model_validate(raw)

    task, server_id, client_id = await _create_task(tm, params, handler_name)
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

                if isinstance(event, TaskStatusUpdateEvent):
                    notification = {
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": {
                            "type": "status",
                            "id": client_id,
                            "status": {
                                "state": str(event.status.state),
                                "timestamp": event.status.timestamp.isoformat()
                                    if event.status.timestamp else None,
                                "message": jsonable_encoder(
                                    event.status.message, exclude_none=True
                                ) if event.status.message else None,
                            },
                            "final": event.final,
                        },
                    }

                elif isinstance(event, TaskArtifactUpdateEvent):
                    notification = {
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": {
                            "type": "artifact",
                            "id": client_id,
                            "artifact": jsonable_encoder(
                                event.artifact, exclude_none=True
                            ),
                        },
                    }

                else:
                    ev = jsonable_encoder(event, exclude_none=True)
                    ev["id"] = client_id
                    notification = {
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": ev,
                    }

                chunk = json.dumps(notification)
                yield f"data: {chunk}\n\n"

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
    async def default_rpc(request: Request):
        payload = await request.json()
        raw = await protocol._handle_raw_async(payload)
        return Response(status_code=204) if raw is None else JSONResponse(
            jsonable_encoder(raw)
        )

    for handler in task_manager.get_handlers():
        @app.post(f"/{handler}/rpc")  # type: ignore
        async def handler_rpc(request: Request, _h=handler):
            payload = await request.json()
            if payload.get("method") in ("tasks/send", "tasks/sendSubscribe"):
                payload.setdefault("params", {})["handler"] = _h
            raw = await protocol._handle_raw_async(payload)
            return Response(status_code=204) if raw is None else JSONResponse(
                jsonable_encoder(raw)
            )

        if event_bus:
            @app.post(f"/{handler}")  # type: ignore
            async def handler_alias(request: Request, _h=handler):
                payload = await request.json()
                if payload.get("method") == "tasks/sendSubscribe" and "params" in payload:
                    try:
                        return await _streaming_send_subscribe(
                            payload, task_manager, event_bus, _h
                        )
                    except Exception as exc:
                        logger.error("[transport.http] streaming failed", exc_info=True)
                        raise HTTPException(status_code=500, detail=str(exc)) from exc
                payload.setdefault("params", {})["handler"] = _h
                raw = await protocol._handle_raw_async(payload)
                return Response(status_code=204) if raw is None else JSONResponse(
                    jsonable_encoder(raw)
                )

        logger.debug("[transport.http] routes registered for handler %s", handler)

__all__ = ["setup_http"]
