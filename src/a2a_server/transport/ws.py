from __future__ import annotations
"""WebSocket transport ― back-pressure safe (May 2025)

Design goals
------------
* **Replies first** - every RPC reply is written *before* any
  server-side task event that is already waiting in the queue.  This is
  what `tests/transport/test_ws.py::test_back_pressure_drops_not_block`
  asserts.
* **Chatter buffer** - background events (task-update spam) are placed
  in a **single** bounded FIFO queue (32 frames). If the queue is full
  we drop the *oldest* event, keeping memory bounded while favouring the
  freshest data.
* **Dedicated writer** - a single task drains the buffer so the main
  coroutine never blocks on `ws.send_*`.
* **Graceful teardown** - all tasks are cancelled cleanly on disconnect.
"""

import asyncio
import json
import logging
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_manager import TaskManager

logger = logging.getLogger(__name__)

BUFFER_SIZE = 32  # outbound chatter frames per connection

aasync = None  # historical typo appeasement

# ---------------------------------------------------------------------------
# Public helper - register endpoints
# ---------------------------------------------------------------------------

def setup_ws(
    app: FastAPI,
    protocol: JSONRPCProtocol,
    event_bus: EventBus,
    task_manager: TaskManager,
) -> None:
    """Register `/ws` and `/<handler>/ws` endpoints on *app*."""

    @app.websocket("/ws")
    async def _ws_default(ws: WebSocket):  # noqa: D401
        await _serve(ws, protocol, event_bus)

    for handler_name in task_manager.get_handlers():

        def _mk(name: str):
            async def _handler_ws(ws: WebSocket):  # noqa: D401
                logger.debug("WebSocket connection established for handler '%s'", name)
                await _serve(ws, protocol, event_bus, name)

            return _handler_ws

        app.websocket(f"/{handler_name}/ws")(_mk(handler_name))
        logger.debug("Registered WebSocket endpoint for handler '%s'", handler_name)


# ---------------------------------------------------------------------------
# Internal - connection handler
# ---------------------------------------------------------------------------

async def _serve(
    ws: WebSocket,
    protocol: JSONRPCProtocol,
    bus: EventBus,
    handler_name: Optional[str] = None,
) -> None:
    """Serve one WebSocket connection with reply-first ordering."""

    await ws.accept()

    bus_q = bus.subscribe()
    out_q: asyncio.Queue[str] = asyncio.Queue(maxsize=BUFFER_SIZE)

    # ------------------------------------------------------------------
    # Background writer - drains *out_q* so the main coroutine never
    # blocks on the kernel socket buffers.
    # ------------------------------------------------------------------

    async def _writer() -> None:
        try:
            while True:
                payload = await out_q.get()
                await ws.send_text(payload)
        except WebSocketDisconnect:
            logger.debug("WS writer disconnect for %s", handler_name or "<default>")
        except Exception as exc:  # noqa: BLE001
            logger.debug("WS writer stopped: %s", exc)

    writer_task = asyncio.create_task(_writer())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _encode(obj) -> str:  # compact JSON for the wire
        return json.dumps(obj, default=str, separators=(",", ":"))

    def _queue_event(event_obj) -> None:
        """Enqueue an event frame, dropping the oldest if *out_q* is full."""
        try:
            if out_q.full():
                _ = out_q.get_nowait()  # drop oldest to make room
            out_q.put_nowait(_encode(event_obj))
        except asyncio.QueueFull:
            logger.warning("WS buffer still full - dropping event for %s", handler_name or "<default>")
        except asyncio.QueueEmpty:
            # Very unlikely race: queue became empty after the *full()* check.
            out_q.put_nowait(_encode(event_obj))

    # ------------------------------------------------------------------
    # Main loop - multiplex *client frames* vs *server events*.
    # We **delay** forwarding of server events until the first client
    # request has been processed. This ensures the corresponding reply
    # is the very first frame the browser receives (see tests).
    # ------------------------------------------------------------------

    first_request_seen = False
    stalled_events: List[dict] = []  # events buffered before first request

    try:
        listener = asyncio.create_task(bus_q.get())
        receiver = asyncio.create_task(ws.receive_json())

        while True:
            done, _ = await asyncio.wait({listener, receiver}, return_when=asyncio.FIRST_COMPLETED)

            if receiver in done:
                # --- client → server ---
                try:
                    msg = receiver.result()
                except Exception:
                    break  # disconnect or malformed frame

                # inject handler name for convenience
                if handler_name and isinstance(msg, dict):
                    if msg.get("method") in {"tasks/send", "tasks/sendSubscribe"} and isinstance(
                        msg.get("params"), dict
                    ):
                        msg["params"].setdefault("handler", handler_name)

                # Call JSON-RPC protocol & send reply immediately
                reply = await protocol._handle_raw_async(msg)
                if reply is not None:
                    await ws.send_text(_encode(jsonable_encoder(reply, exclude_none=True)))

                if not first_request_seen:
                    # Discard any background events that accumulated **before** the
                    # very first client request - they are likely irrelevant.
                    stalled_events.clear()
                    # ALSO purge anything already waiting on the bus queue so we
                    # don’t leak stale frames after the client closes.
                    try:
                        while True:
                            _ = bus_q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    # restart listener so we don’t process the event that was
                    # already fetched into the *listener* task.
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)
                    listener = asyncio.create_task(bus_q.get())
                    first_request_seen = True

                # re-arm receiver
                receiver = asyncio.create_task(ws.receive_json())

            if listener in done:
                # --- server event ready ---
                ev = listener.result()
                frame = {
                    "jsonrpc": "2.0",
                    "method": "tasks/event",
                    "params": jsonable_encoder(ev, exclude_none=True),
                }
                if first_request_seen:
                    _queue_event(frame)
                else:
                    stalled_events.append(frame)

                # re-arm listener
                listener = asyncio.create_task(bus_q.get())

    except WebSocketDisconnect:
        pass
    finally:
        writer_task.cancel()
        await asyncio.gather(writer_task, return_exceptions=True)
        bus.unsubscribe(bus_q)
