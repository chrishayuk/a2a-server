# File: tests/server/test_methods.py

import pytest
from pydantic import ValidationError
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.methods import register_methods
from a2a.server.task_manager import TaskManager, TaskNotFound
from a2a.server.pubsub import EventBus
from a2a.models.spec import TextPart, Message, Role, TaskState


@pytest.fixture
def protocol_manager():
    """
    Set up a fresh EventBus, TaskManager, and JSONRPCProtocol
    with registered A2A methods.
    """
    event_bus = EventBus()
    manager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()
    register_methods(protocol, manager)
    return protocol, manager


@pytest.mark.asyncio
async def test_send_and_get(protocol_manager):
    protocol, manager = protocol_manager
    # Valid send params
    params = {
        "id": "ignored",
        "sessionId": None,
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": "Hello Methods"}]
        }
    }
    send_handler = protocol._methods["tasks/send"]
    result = await send_handler("tasks/send", params)
    # Alias keys present
    assert isinstance(result.get("id"), str)
    assert isinstance(result.get("sessionId"), str)
    # Enum returned for state
    assert result["status"]["state"] == TaskState.submitted

    # Get the same task
    task_id = result["id"]
    get_handler = protocol._methods["tasks/get"]
    get_result = await get_handler("tasks/get", {"id": task_id})
    assert get_result["id"] == task_id
    assert get_result["status"]["state"] == TaskState.submitted


@pytest.mark.asyncio
async def test_send_invalid_params(protocol_manager):
    protocol, _ = protocol_manager
    send_handler = protocol._methods["tasks/send"]
    # Missing required 'message'
    with pytest.raises(ValidationError):
        await send_handler("tasks/send", {"id": "ignored", "sessionId": None})


@pytest.mark.asyncio
async def test_cancel(protocol_manager):
    protocol, manager = protocol_manager
    # Create then cancel a task
    send_res = await protocol._methods["tasks/send"](
        "tasks/send",
        {"id": "ignored", "sessionId": None, "message": {"role": "user", "parts": [{"type": "text", "text": "To be canceled"}]}}
    )
    task_id = send_res["id"]

    cancel_handler = protocol._methods["tasks/cancel"]
    cancel_res = await cancel_handler("tasks/cancel", {"id": task_id})
    assert cancel_res is None
    # Manager should reflect canceled state
    task = await manager.get_task(task_id)
    assert task.status.state == TaskState.canceled


@pytest.mark.asyncio
async def test_cancel_nonexistent(protocol_manager):
    protocol, _ = protocol_manager
    cancel_handler = protocol._methods["tasks/cancel"]
    with pytest.raises(TaskNotFound):
        await cancel_handler("tasks/cancel", {"id": "nonexistent"})


@pytest.mark.asyncio
async def test_send_subscribe_and_resubscribe(protocol_manager):
    protocol, manager = protocol_manager
    # sendSubscribe works like send
    sub_res = await protocol._methods["tasks/sendSubscribe"](
        "tasks/sendSubscribe",
        {"id": "ignored", "sessionId": None, "message": {"role": "user", "parts": [{"type": "text", "text": "Sub me"}]}}
    )
    assert isinstance(sub_res.get("id"), str)
    assert sub_res["status"]["state"] == TaskState.submitted

    # resubscribe is a no-op stub
    resub_res = await protocol._methods["tasks/resubscribe"](
        "tasks/resubscribe", {"id": sub_res["id"]}
    )
    assert resub_res is None
    # tasks_by_state unaffected
    submitted_tasks = manager.tasks_by_state(TaskState.submitted)
    assert any(t.id == sub_res["id"] for t in submitted_tasks)
