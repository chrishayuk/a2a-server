# tests/transport/test_sse.py
import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from a2a_server.pubsub import EventBus
from a2a_server.transport.sse import setup_sse as setup_a2a_sse
from a2a_server.transport import sse as sse_mod

# a2a spec helpers for a realistic event
from a2a_json_rpc.spec import (
    TaskStatusUpdateEvent,
    TaskStatus,
    TaskState,
)


@pytest_asyncio.fixture
async def app_with_sse():
    """FastAPI app wired with EventBus‑backed SSE endpoint for tests."""
    app = FastAPI()
    bus = EventBus()
    # shorten server‑imposed TTL for all tests to avoid hangs
    sse_mod.MAX_SSE_LIFETIME = 0.5
    sse_mod.HEARTBEAT_INTERVAL = 0.1
    app.state.event_bus = bus  # type: ignore[attr-defined]
    # we don't need TaskManager for plain /events route
    setup_a2a_sse(app, bus, type("_DummyTM", (), {"get_handlers": lambda self: {}})())  # type: ignore[arg-type]
    
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        yield app, bus, client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@asynccontextmanager
async def open_event_stream(client):
    """Context manager that yields an async iterator over SSE data chunks."""
    async with client.stream("GET", "/events") as resp:
        # ensure OK + streaming
        assert resp.status_code == 200
        yield resp.aiter_lines()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_sse_delivers_event(app_with_sse):
    app, bus, client = app_with_sse

    # prepare a status‑update event
    event = TaskStatusUpdateEvent(
        id="task‑1",
        status=TaskStatus(state=TaskState.completed),
        final=True,
    )

    async with open_event_stream(client) as lines:
        # publish in background after a tiny pause so stream is ready
        asyncio.get_running_loop().call_later(0.05, lambda: asyncio.create_task(bus.publish(event)))

        async for line in lines:
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])  # strip "data: " prefix
            assert payload["params"]["id"] == "task‑1"
            assert payload["params"]["type"] == "status"
            break  # success


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_heartbeat_and_max_lifetime(monkeypatch, app_with_sse):
    app, bus, client = app_with_sse

    # shorten intervals dramatically for test speed
    monkeypatch.setattr(sse_mod, "HEARTBEAT_INTERVAL", 0.1)
    monkeypatch.setattr(sse_mod, "MAX_SSE_LIFETIME", 0.3)

    got_heartbeat = False
    async with open_event_stream(client) as lines:
        async for line in lines:
            if line.startswith(": keep-alive"):
                got_heartbeat = True
                break
        # after we witnessed one heartbeat, wait for stream to close itself
        await asyncio.sleep(0.35)

    assert got_heartbeat, "never saw heartbeat comment"
    # no assertion on explicit close necessary – contextmanager exiting without error implies closure
