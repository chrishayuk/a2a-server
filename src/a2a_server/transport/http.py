# a2a_server/transport/http.py
"""
Correct solution: Deduplication in _dispatch as the ultimate truth
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
REQUEST_TIMEOUT: float = float(os.getenv("JSONRPC_TIMEOUT", 15.0))    # seconds

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_terminal(state: TaskState) -> bool:
    return state in {TaskState.completed, TaskState.canceled, TaskState.failed}

def _ensure_task_id(payload: JSONRPCRequest) -> None:
    """Only assign UUID if no ID is present."""
    if payload.method == "tasks/send" and isinstance(payload.params, dict):
        if not payload.params.get("id"):
            payload.params["id"] = str(uuid.uuid4())
            logger.debug(f"🆔 Assigned new task ID: {payload.params['id']}")
        else:
            logger.debug(f"🆔 Using client task ID: {payload.params['id']}")

async def _create_task(
    tm: TaskManager,
    params: TaskSendParams,
    handler: str | None,
) -> Tuple[Task, str, str]:
    """Helper that works with both new and legacy TaskManager signatures."""
    client_id = params.id
    original = inspect.unwrap(tm.create_task)
    bound: Callable[..., Awaitable[Task]] = original.__get__(tm, tm.__class__)
    sig = inspect.signature(original)

    if "task_id" in sig.parameters:
        task = await bound(
            params.message,
            session_id=params.session_id,
            handler_name=handler,
            task_id=client_id,
        )
        return task, task.id, task.id

    task = await bound(params.message, session_id=params.session_id, handler_name=handler)
    server_id = task.id
    if client_id and client_id != server_id:
        async with tm._lock:
            tm._aliases[client_id] = server_id
    else:
        client_id = server_id
    return task, server_id, client_id

# ---------------------------------------------------------------------------
# SSE implementation - tasks/sendSubscribe
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

    # DEDUPLICATION: Check for duplicates before creating task
    try:
        from a2a_server.deduplication import deduplicator
        
        session_id = params.session_id or 'default'
        message = params.message
        
        logger.info(f"🔍 SSE dedup check: session={session_id}, handler={handler_name}")
        
        existing_task_id = await deduplicator.check_duplicate(
            tm, session_id, message, handler_name or 'default'
        )
        
        if existing_task_id:
            logger.info(f"🔄 SSE found duplicate: {existing_task_id}")
            try:
                task = await tm.get_task(existing_task_id)
                server_id, client_id = task.id, params.id or task.id
            except Exception as e:
                logger.warning(f"Failed to get existing SSE task {existing_task_id}: {e}")
                # Fall through to create new task
                existing_task_id = None
        
        if not existing_task_id:
            # Create new task
            try:
                task, server_id, client_id = await _create_task(tm, params, handler_name)
                
                # Record for future deduplication
                await deduplicator.record_task(
                    tm, session_id, message, handler_name or 'default', task.id
                )
                logger.info(f"✅ SSE recorded task: {task.id}")
                
            except ValueError as exc:
                if "already exists" in str(exc).lower():
                    task = await tm.get_task(params.id)
                    server_id, client_id = task.id, params.id
                else:
                    raise
    
    except Exception as e:
        logger.warning(f"⚠️ SSE deduplication failed, continuing: {e}")
        # Fall back to normal creation
        try:
            task, server_id, client_id = await _create_task(tm, params, handler_name)
        except ValueError as exc:
            if "already exists" in str(exc).lower():
                task = await tm.get_task(params.id)
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
# Route-mount helper (public)
# ---------------------------------------------------------------------------

def setup_http(
    app: FastAPI,
    protocol: JSONRPCProtocol,
    task_manager: TaskManager,
    event_bus: Optional[EventBus] = None,
) -> None:
    """Mount endpoints with deduplication in _dispatch as ultimate truth."""

    # ---- _dispatch with deduplication - ULTIMATE TRUTH -----

    async def _dispatch(req: JSONRPCRequest) -> Response:
        """Ultimate truth: All requests go through deduplication here."""
        if not isinstance(req.params, dict):
            return JSONResponse({"detail": "params must be an object"}, status_code=422)

        # DEDUPLICATION: Ultimate truth for all task creation
        if req.method in ["tasks/send", "tasks/sendSubscribe"]:
            try:
                from a2a_server.deduplication import deduplicator
                
                # Extract parameters
                handler_name = req.params.get('handler', 'default')
                session_id = req.params.get('session_id', 'default')
                message = req.params.get('message', {})
                
                # Check for duplicates
                logger.info(f"🔍 _dispatch dedup check: session={session_id}, handler={handler_name}")
                
                existing_task_id = await deduplicator.check_duplicate(
                    task_manager, session_id, message, handler_name
                )
                
                if existing_task_id:
                    logger.info(f"🔄 _dispatch found duplicate: {existing_task_id}")
                    try:
                        from a2a_json_rpc.spec import Task as TaskSpec
                        existing_task = await task_manager.get_task(existing_task_id)
                        task_dict = TaskSpec.model_validate(existing_task.model_dump()).model_dump(exclude_none=True, by_alias=True)
                        
                        # Return in proper JSON-RPC format
                        response = {"jsonrpc": "2.0", "id": req.id, "result": task_dict}
                        return JSONResponse(response)
                        
                    except Exception as e:
                        logger.warning(f"Failed to return existing task {existing_task_id}: {e}")
                        # Continue with normal processing if we can't return existing task
            
            except Exception as e:
                logger.warning(f"⚠️ _dispatch deduplication failed, continuing: {e}")

        # Normal processing through protocol
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                raw = await protocol._handle_raw_async(req.model_dump())
                
                # Record new tasks for future deduplication
                if req.method in ["tasks/send", "tasks/sendSubscribe"] and raw and isinstance(raw, dict):
                    try:
                        from a2a_server.deduplication import deduplicator
                        
                        result = raw.get('result', {})
                        if isinstance(result, dict) and result.get('id'):
                            handler_name = req.params.get('handler', 'default')
                            session_id = req.params.get('session_id', 'default')
                            message = req.params.get('message', {})
                            task_id = result['id']
                            
                            await deduplicator.record_task(
                                task_manager, session_id, message, handler_name, task_id
                            )
                            logger.info(f"✅ _dispatch recorded task: {task_id}")
                    
                    except Exception as e:
                        logger.warning(f"⚠️ _dispatch failed to record task: {e}")
                        
        except TimeoutError:
            return JSONResponse({"detail": "Handler timed-out"}, status_code=504)

        return Response(status_code=204) if raw is None else JSONResponse(jsonable_encoder(raw))

    # ---- All endpoints route through _dispatch -----

    @app.post("/rpc")
    async def _default_rpc(payload: JSONRPCRequest = Body(...)):
        _ensure_task_id(payload)
        return await _dispatch(payload)

    for handler in task_manager.get_handlers():

        @app.post(f"/{handler}/rpc")
        async def _handler_rpc(
            payload: JSONRPCRequest = Body(...),
            _h: str = handler,
        ):
            _ensure_task_id(payload)
            if payload.method in {"tasks/send", "tasks/sendSubscribe"} and isinstance(payload.params, dict):
                payload.params.setdefault("handler", _h)
            return await _dispatch(payload)

        if event_bus:

            @app.post(f"/{handler}")
            async def _handler_alias(
                payload: JSONRPCRequest = Body(...),
                _h: str = handler,
            ):
                _ensure_task_id(payload)

                if payload.method == "tasks/sendSubscribe":
                    return await _stream_send_subscribe(payload, task_manager, event_bus, _h)

                if isinstance(payload.params, dict):
                    payload.params.setdefault("handler", _h)
                return await _dispatch(payload)

        logger.debug("[transport.http] routes registered for handler %s", handler)

__all__ = ["setup_http", "REQUEST_TIMEOUT"]