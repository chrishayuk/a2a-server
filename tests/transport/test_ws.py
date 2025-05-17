from __future__ import annotations
"""WebSocket transport integration tests (async, self-hosted).

This version fixes lingering teardown hangs by **force-awaiting** the Uvicorn
`serve()` task with a timeout and, if required, cancelling it explicitly.
"""

import json
import asyncio
import socket
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
import uvicorn
import websockets
from fastapi import FastAPI
from websockets.exceptions import ConnectionClosedOK

from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_server.methods import register_methods
from a2a_server.pubsub import EventBus
from a2a_server.tasks.handlers.echo_handler import EchoHandler
from a2a_server.tasks.task_manager import TaskManager
from a2a_server.transport.ws import setup_ws

# ── silence noisy libs ────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# ---------------------------------------------------------------------------
# Helper: pick a free TCP port on localhost
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Fixture: run Uvicorn in-loop (no threads) and guarantee clean shutdown
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
def uvicorn_server():
    """Return a callable wrapping *app* in an async context-manager."""

    def _runner(app: FastAPI):
        @asynccontextmanager
        async def _cm():
            port = _free_port()
            cfg = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                loop="asyncio",
                lifespan="off",          # avoid Starlette lifespan races
                log_level="warning",
            )
            server = uvicorn.Server(cfg)
            serve_task = asyncio.create_task(server.serve())

            # wait until the server is ready to accept connections
            while not server.started:  # type: ignore[attr-defined]
                await asyncio.sleep(0.05)

            try:
                yield SimpleNamespace(host="127.0.0.1", port=port)
            finally:
                # Request shutdown and wait up to 2 s – if still alive, cancel
                server.should_exit = True
                try:
                    await asyncio.wait_for(serve_task, timeout=2)
                except asyncio.TimeoutError:
                    serve_task.cancel()
                    await asyncio.gather(serve_task, return_exceptions=True)
        return _cm()

    return _runner


# ---------------------------------------------------------------------------
# Helper: minimal FastAPI app with WS transport wired
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    bus = EventBus()
    tm = TaskManager(bus)
    tm.register_handler(EchoHandler(), default=True)

    proto = JSONRPCProtocol()
    register_methods(proto, tm)

    app = FastAPI()
    setup_ws(app, proto, bus, tm)
    app.state.bus = bus  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_roundtrip(uvicorn_server):
    app = _make_app()
    async with uvicorn_server(app) as srv:
        uri = f"ws://{srv.host}:{srv.port}/ws"
        async with websockets.connect(uri) as ws:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tasks/send",
                        "params": {
                            "id": "ignored",
                            "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
                        },
                    }
                )
            )

            resp = json.loads(await ws.recv())
            assert resp["id"] == 1
            task_id = resp["result"]["id"]

            # Wait for *completed* event (5 s watchdog)
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                evt = json.loads(raw)
                if (
                    evt.get("method") == "tasks/event"
                    and evt["params"].get("final")
                    and evt["params"]["id"] == task_id
                ):
                    assert evt["params"]["status"]["state"] == "completed"
                    break


@pytest.mark.asyncio
async def test_back_pressure_drops_not_block(uvicorn_server):
    app = _make_app()
    bus = app.state.bus  # type: ignore[attr-defined]

    async with uvicorn_server(app) as srv:
        uri = f"ws://{srv.host}:{srv.port}/ws"
        async with websockets.connect(uri) as ws:
            # Flood queue (> buffer size = 32)
            for i in range(40):
                await bus.publish(
                    type("Evt", (), {"id": f"t{i}", "model_dump": lambda _s, exclude_none=True: {"dummy": i}})()
                )

            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 99, "method": "tasks/get", "params": {"id": "n/a"}}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert reply["id"] == 99

        # Connection closed; extra recv should raise quickly
        with pytest.raises(ConnectionClosedOK):
            await ws.recv()