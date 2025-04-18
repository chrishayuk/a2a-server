import pytest
from a2a.task_manager import TaskManager, TaskState
from a2a.models.spec import TextPart, Message

@pytest.mark.asyncio
async def test_create_and_complete():
    tm = TaskManager()
    part = TextPart(type="text", text="hi")
    msg = Message(role="user", parts=[part])
    task = await tm.create_task(msg)
    assert task.status.state == TaskState.submitted
    await tm.update_status(task.id, TaskState.completed)
    assert (await tm.get_task(task.id)).status.state == TaskState.completed
