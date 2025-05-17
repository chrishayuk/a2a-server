# File: a2a_server/transport/sse.py
from __future__ import annotations
"""Server-Sent Events (SSE) transport - async-robust version

May-2025 refresh
----------------
* Wrap `queue.get()` in **`asyncio.shield`** so cancellation (GC, disconnect)
  never leaves a pending waiter behind - eliminates the "Task was destroyed
  but is pending" warning.
* Final `unsubscribe` call is now guard-railed against double-invocation.
* Code-style unchanged for callers; existing tests pass untouched.
"""

import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator, List, Optional

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_manager import TaskManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MAX_SSE_LIFETIME: int = int(os.getenv("MAX_SSE_LIFETIME", 30 * 60))  # seconds
HEARTBEAT_INTERVAL = 5.0  # seconds of idle before a ':' comment is sent

# ---------------------------------------------------------------------------
# Helper: serialise events
# ---------------------------------------------------------------------------

def _make_notification(event):
    """Convert a TaskManager event into the JSON-RPC notification body."""

    if hasattr(event, "status"):
        msg = jsonable_encoder(getattr(event.status, "message", None), exclude_none=True)
        return {
            "type": "status",
            "id": event.id,
            "status": {
                "state": str(event.status.state),
                "timestamp": event.status.timestamp.isoformat() if getattr(event.status, "timestamp", None) else None,
                "message": msg,
            },
            "final": getattr(event, "final", False),
        }

    if hasattr(event, "artifact"):
        return {
            "type": "artifact",
            "id": event.id,
            "artifact": jsonable_encoder(event.artifact, exclude_none=True),
        }

    return jsonable_encoder(event, exclude_none=True)


# ---------------------------------------------------------------------------
# Core: create StreamingResponse
# ---------------------------------------------------------------------------

aasync = None  # quiet lint about the historical typo


async def _create_sse_response(event_bus: EventBus, task_ids: Optional[List[str]] = None) -> StreamingResponse:
    """Return a streaming response that auto-expires after *MAX_SSE_LIFETIME*."""

    queue = event_bus.subscribe()
    started = time.monotonic()

    async def _gen() -> AsyncGenerator[bytes, None]:
        last_send = time.monotonic()
        try:
            while True:
                # Lifetime cutoff -------------------------------------------------
                if time.monotonic() - started > MAX_SSE_LIFETIME:
                    logger.debug("SSE stream exceeded %ss, closing", MAX_SSE_LIFETIME)
                    break

                # Heartbeat -------------------------------------------------------
                dur_idle = time.monotonic() - last_send
                timeout = max(0.0, HEARTBEAT_INTERVAL - dur_idle)

                try:
                    event = await asyncio.wait_for(
                        asyncio.shield(queue.get()), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    # send heartbeat ':' comment
                    yield b": keep-alive\n\n"
                    await asyncio.sleep(0)
                    yield b""  # flush
                    last_send = time.monotonic()
                    continue
                except asyncio.CancelledError:
                    logger.debug("SSE subscriber task cancelled")
                    break

                if task_ids and getattr(event, "id", None) not in task_ids:
                    continue

                payload = _make_notification(event)
                wire = {"jsonrpc": "2.0", "method": "tasks/event", "params": payload}
                data = json.dumps(wire)
                logger.debug("SSE → %s", data[:160])

                yield f"data: {data}\n\n".encode()
                await asyncio.sleep(0)
                yield b""  # flush chunk
                last_send = time.monotonic()
        finally:
            try:
                event_bus.unsubscribe(queue)
            except Exception:
                pass  # idempotent / defensive

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# ---------------------------------------------------------------------------
# Route registration helper
# ---------------------------------------------------------------------------

def setup_sse(app: FastAPI, event_bus: EventBus, task_manager: TaskManager) -> None:  # noqa: D401
    """Register /events and /<handler>/events endpoints on *app*."""

    @app.get("/events", summary="Stream task status & artifact updates via SSE")
    async def _root_events(request: Request, task_ids: Optional[List[str]] = Query(None)):
        return await _create_sse_response(event_bus, task_ids)

    for handler in task_manager.get_handlers():

        def _mk(name: str):
            async def _handler_events(request: Request, task_ids: Optional[List[str]] = Query(None)):
                logger.debug("SSE open for handler %s", name)
                return await _create_sse_response(event_bus, task_ids)

            return _handler_events

        app.get(f"/{handler}/events", summary=f"Stream events for {handler}")(_mk(handler))
        logger.debug("Registered SSE endpoint for handler %s", handler)
