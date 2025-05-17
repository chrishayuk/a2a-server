# File: tests/test_methods.py
from __future__ import annotations
"""async-native tests for a2a_server.methods (TaskGroup edition).

These tests exercise the public JSON-RPC surface end-to-end with a real
TaskManager + EchoHandler running inside an asyncio.TaskGroup.
"""

import asyncio
from typing import Any, Dict

import pytest
import pytest_asyncio
from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_json_rpc.spec import (
    JSONRPCRequest,
    Message,
    Role,
    TaskState,
    TextPart,
)

from a2a_server.methods import register_methods
from a2a_server.pubsub import EventBus
from a2a_server.tasks.handlers.echo_handler import EchoHandler
from a2a_server.tasks.task_manager import TaskManager

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _json_rpc(id_: str, method: str, params: Dict[str, Any] | None = None) -> JSONRPCRequest:  # noqa: ANN001
    """Convenience builder for JSON-RPC requests."""
    return JSONRPCRequest(id=id_, jsonrpc="2.0", method=method, params=params or {})


async def _call(proto: JSONRPCProtocol, req: JSONRPCRequest):  # noqa: ANN001
    """Round-trip *req* through *proto* and return the *result* field."""
    raw = await proto._handle_raw_async(req.model_dump())
    if raw is None:  # Notification path - directly call registered handler
        handler = proto._methods[req.method]  # type: ignore[attr-defined]
        return await handler(req.method, req.params or {})

    if raw.get("error"):
        raise RuntimeError(raw["error"])
    return raw.get("result")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def proto_mgr():
    ev = EventBus()
    tm = TaskManager(ev)
    tm.register_handler(EchoHandler(), default=True)

    proto = JSONRPCProtocol()
    register_methods(proto, tm)

    yield proto, tm

    await tm.shutdown()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_get_complete(proto_mgr):
    proto, _ = proto_mgr
    msg = Message(role=Role.user, parts=[TextPart(type="text", text="hello")])

    res = await _call(proto, _json_rpc("1", "tasks/send", {"id": "ignored", "message": msg.model_dump()}))
    tid = res["id"]
    assert res["status"]["state"] == TaskState.submitted

    # wait until task completed
    for _ in range(15):
        await asyncio.sleep(0.1)
        fin = await _call(proto, _json_rpc("g", "tasks/get", {"id": tid}))
        if fin["status"]["state"] == TaskState.completed:
            break
    assert fin["artifacts"][0]["parts"][0]["text"] == "Echo: hello"


@pytest.mark.asyncio
async def test_send_invalid_missing_message(proto_mgr):
    proto, _ = proto_mgr
    with pytest.raises(Exception):
        await _call(proto, _json_rpc("bad", "tasks/send", {"id": "ignored"}))


@pytest.mark.asyncio
async def test_cancel_and_not_found(proto_mgr):
    proto, tm = proto_mgr
    payload = {
        "id": "ignored",
        "message": {"role": "user", "parts": [{"type": "text", "text": "bye"}]}
    }
    tid = (await _call(proto, _json_rpc("s", "tasks/send", payload)))["id"]

    await _call(proto, _json_rpc("c", "tasks/cancel", {"id": tid}))
    await asyncio.sleep(0.1)
    assert (await tm.get_task(tid)).status.state == TaskState.canceled

    # cancel nonexistent should raise RuntimeError (wrapped TaskNotFound)
    with pytest.raises(RuntimeError):
        await _call(proto, _json_rpc("c2", "tasks/cancel", {"id": "nope"}))


@pytest.mark.asyncio
async def test_send_subscribe_resubscribe(proto_mgr):
    proto, _ = proto_mgr
    msg = {"role": "user", "parts": [{"type": "text", "text": "sub"}]}

    sub = await _call(proto, _json_rpc("1", "tasks/sendSubscribe", {"id": "ignored", "message": msg}))
    tid = sub["id"]

    assert await _call(proto, _json_rpc("2", "tasks/resubscribe", {"id": tid})) is None

    # wait completion
    for _ in range(15):
        await asyncio.sleep(0.1)
        fin = await _call(proto, _json_rpc("g", "tasks/get", {"id": tid}))
        if fin["status"]["state"] == TaskState.completed:
            break
    assert fin["status"]["state"] == TaskState.completed


@pytest.mark.asyncio
async def test_cancel_pending_tasks_helper(proto_mgr):
    proto, _ = proto_mgr

    # fabricate a stray background task and stuff it into legacy set
    async def _sleep():
        await asyncio.sleep(10)

    stray = asyncio.create_task(_sleep())

    import a2a_server.methods as m
    tasks_set = getattr(m, "_background_tasks", None)
    if tasks_set is None:
        tasks_set = set()
        setattr(m, "_background_tasks", tasks_set)
    tasks_set.add(stray)

    await proto.cancel_pending_tasks()
    await asyncio.sleep(0)  # let cancellation propagate
    assert stray.cancelled()
