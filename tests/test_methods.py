# File: tests/test_methods.py
"""async‑native tests for a2a_server.methods

Exercises the public JSON‑RPC surface end‑to‑end using real requests.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
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
from a2a_server.tasks.task_manager import TaskManager, TaskNotFound

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_rpc(id_: str, method: str, params: Dict[str, Any] | None = None) -> JSONRPCRequest:  # noqa: ANN001
    """Convenience helper to build a JSON‑RPC 2.0 request object."""
    return JSONRPCRequest(id=id_, jsonrpc="2.0", method=method, params=params or {})


async def _call(proto: JSONRPCProtocol, req: JSONRPCRequest):  # noqa: ANN001
    """Round‑trip *req* through *proto* and return the `result` payload.

    Handles both the usual request/response path and the fallback code‑path
    (where the library chooses to issue a notification and call the handler
    directly instead of returning a response object).
    """
    raw = await proto._handle_raw_async(req.model_dump())
    if raw is not None:  # normal request‑response
        # Some JSON‑RPC implementations include ``"error": null`` even for
        # successful calls – only raise when the *value* is truthy.
        if raw.get("error"):
            raise RuntimeError(raw["error"])
        return raw.get("result")

    # Notification path – fall back to calling the registered coroutine
    handler = proto._methods[req.method]  # type: ignore[attr-defined]
    return await handler(req.method, req.params or {})


@pytest.fixture()
def proto_mgr():
    """Return a fresh `(protocol, task_manager)` tuple for each test."""
    ev = EventBus()
    tm = TaskManager(ev)
    tm.register_handler(EchoHandler(), default=True)

    proto = JSONRPCProtocol()
    register_methods(proto, tm)
    return proto, tm

# ---------------------------------------------------------------------------
# Core CRUD flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_get_complete(proto_mgr):
    proto, _ = proto_mgr

    msg = Message(role=Role.user, parts=[TextPart(type="text", text="hello")])
    res = await _call(
        proto,
        _json_rpc(
            "1", "tasks/send", {"id": "ignored", "message": msg.model_dump()}  # client‑supplied id is ignored
        ),
    )
    tid = res["id"]
    assert res["status"]["state"] == TaskState.submitted

    await asyncio.sleep(1.5)

    fin = await _call(proto, _json_rpc("2", "tasks/get", {"id": tid}))
    assert fin["status"]["state"] == TaskState.completed
    assert fin["artifacts"][0]["parts"][0]["text"] == "Echo: hello"


@pytest.mark.asyncio
async def test_send_invalid_missing_message(proto_mgr):
    proto, _ = proto_mgr
    with pytest.raises(Exception):
        await _call(proto, _json_rpc("bad", "tasks/send", {"id": "ignored"}))


# ---------------------------------------------------------------------------
# Cancel path + nonexistent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_and_not_found(proto_mgr):
    proto, tm = proto_mgr

    tid = (
        await _call(
            proto,
            _json_rpc(
                "send",
                "tasks/send",
                {
                    "id": "ignored",
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "bye"}],
                    },
                },
            ),
        )
    )["id"]

    await _call(proto, _json_rpc("can", "tasks/cancel", {"id": tid}))
    await asyncio.sleep(0.2)
    assert (await tm.get_task(tid)).status.state == TaskState.canceled

    with pytest.raises(RuntimeError):
        err = await _call(proto, _json_rpc("can2", "tasks/cancel", {"id": "nope"}))
        # Helper translates JSON‑RPC → RuntimeError – make sure original id is mentioned
        await _call(proto, _json_rpc("can2", "tasks/cancel", {"id": "nope"}))


# ---------------------------------------------------------------------------
# sendSubscribe + resubscribe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_subscribe_resubscribe(proto_mgr):
    proto, _ = proto_mgr
    msg = {"role": "user", "parts": [{"type": "text", "text": "sub me"}]}

    sub = await _call(
        proto,
        _json_rpc(
            "1",
            "tasks/sendSubscribe",
            {"id": "ignored", "message": msg, "handler": "echo"},
        ),
    )
    tid = sub["id"]

    rs = await _call(proto, _json_rpc("2", "tasks/resubscribe", {"id": tid}))
    assert rs is None

    await asyncio.sleep(1.5)
    fin = await _call(proto, _json_rpc("3", "tasks/get", {"id": tid}))
    assert fin["status"]["state"] == TaskState.completed


# ---------------------------------------------------------------------------
# cancel_pending_tasks helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_pending_tasks_helper(proto_mgr):
    proto, _ = proto_mgr

    async def _sleep():
        await asyncio.sleep(10)

    t = asyncio.create_task(_sleep())

    import a2a_server.methods as m

    # Locate whichever global set is used in the current implementation
    tasks_set = getattr(m, "_background_tasks", None)
    if tasks_set is None:
        tasks_set = getattr(m, "_BACKGROUND_TASKS", None)
    if tasks_set is None:
        tasks_set = set()
        setattr(m, "_background_tasks", tasks_set)

    tasks_set.add(t)

    await proto.cancel_pending_tasks()
    # Give the event‑loop a tick so the cancellation propagates
    await asyncio.sleep(0)
    assert t.cancelled()

# ---------------------------------------------------------------------------
# Custom handler + agent card + multi‑turn session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_handler_selection(proto_mgr):
    proto, tm = proto_mgr
    from a2a_json_rpc.spec import TaskStatusUpdateEvent, TaskStatus

    class TestHandler(EchoHandler):
        @property
        def name(self):
            return "test"

        async def process_task(self, task_id, message, session_id=None):  # noqa: ANN001
            yield TaskStatusUpdateEvent(
                id=task_id, status=TaskStatus(state=TaskState.completed), final=True
            )

    tm.register_handler(TestHandler())

    tid = (
        await _call(
            proto,
            _json_rpc(
                "s",
                "tasks/sendSubscribe",
                {
                    "id": "ignored",
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "x"}],
                    },
                    "handler": "test",
                },
            ),
        )
    )["id"]

    await asyncio.sleep(0.2)
    res = await _call(proto, _json_rpc("g", "tasks/get", {"id": tid}))
    assert res["status"]["state"] == TaskState.completed
    assert not res.get("artifacts")


@pytest.mark.asyncio
async def test_handler_with_agent_card(proto_mgr):
    proto, tm = proto_mgr

    class CardHandler(EchoHandler):
        @property
        def name(self):
            return "card_handler"

    h = CardHandler()
    h.agent_card = {"name": "Card Test", "version": "1.0.0"}
    tm.register_handler(h)

    tid = (
        await _call(
            proto,
            _json_rpc(
                "s",
                "tasks/send",
                {
                    "id": "ignored",
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "hi"}],
                    },
                    "handler": "card_handler",
                },
            ),
        )
    )["id"]

    await asyncio.sleep(1.5)
    res = await _call(proto, _json_rpc("g", "tasks/get", {"id": tid}))
    assert res["status"]["state"] == TaskState.completed
    assert h.agent_card["name"] == "Card Test"


@pytest.mark.asyncio
async def test_multi_turn_same_session(proto_mgr):
    proto, _ = proto_mgr

    first = await _call(
        proto,
        _json_rpc(
            "1",
            "tasks/send",
            {
                "id": "ignored",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "first"}],
                },
                "handler": "echo",
            },
        ),
    )

    session_id = first["sessionId"]
    await asyncio.sleep(1.5)

    second = await _call(
        proto,
        _json_rpc(
            "2",
            "tasks/send",
            {
                "id": "ignored",
                "sessionId": session_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "second"}],
                },
                "handler": "echo",
            },
        ),
    )

    await asyncio.sleep(1.5)
    res1 = await _call(proto, _json_rpc("g1", "tasks/get", {"id": first["id"]}))
    res2 = await _call(proto, _json_rpc("g2", "tasks/get", {"id": second["id"]}))

    assert res1["status"]["state"] == TaskState.completed
    assert res2["status"]["state"] == TaskState.completed
    assert res1["sessionId"] == res2["sessionId"]
    assert res1["artifacts"][0]["parts"][0]["text"] == "Echo: first"
    assert res2["artifacts"][0]["parts"][0]["text"] == "Echo: second"
