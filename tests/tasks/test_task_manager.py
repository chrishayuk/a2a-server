# File: tests/server/test_task_manager.py
import asyncio
from typing import List

import pytest
import pytest_asyncio

from a2a_json_rpc.spec import (
    Artifact,
    Message,
    Role,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    TextPart,
)
from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_manager import TaskManager, TaskNotFound, InvalidTransition
from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_server.tasks.handlers.echo_handler import EchoHandler

# ---------------------------------------------------------------------------
# Helper handlers                                                            
# ---------------------------------------------------------------------------


class SimpleHandler(TaskHandler):
    """Completes immediately (submitted → completed)."""

    @property
    def name(self) -> str:
        return "simple"

    async def process_task(self, task_id, message, session_id=None):  # noqa: D401
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True,
        )


class SlowHandler(TaskHandler):
    """Transitions: submitted → working → completed (0.5 s)."""

    @property
    def name(self) -> str:
        return "slow"

    async def process_task(self, task_id, message, session_id=None):  # noqa: D401
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False,
        )
        await asyncio.sleep(0.5)
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True,
        )

    async def cancel_task(self, task_id: str) -> bool:  # noqa: D401
        return True


class CancellableHandler(TaskHandler):
    """Stays *working* until `cancel_task` is invoked."""

    def __init__(self):
        self._flags: dict[str, bool] = {}

    @property
    def name(self) -> str:  # noqa: D401
        return "cancellable"

    async def process_task(self, task_id, message, session_id=None):  # noqa: D401
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False,
        )
        while not self._flags.get(task_id, False):
            await asyncio.sleep(0.05)
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.canceled),
            final=True,
        )

    async def cancel_task(self, task_id: str) -> bool:  # noqa: D401
        self._flags[task_id] = True
        return True


# ---------------------------------------------------------------------------
# Fixtures                                                                    
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def event_bus():  # noqa: D401
    yield EventBus()


@pytest_asyncio.fixture()
async def task_manager(event_bus):  # noqa: D401
    manager = TaskManager(event_bus)
    manager.register_handler(SimpleHandler(), default=True)
    manager.register_handler(SlowHandler())
    manager.register_handler(CancellableHandler())
    manager.register_handler(EchoHandler())
    yield manager
    await manager.shutdown()


# ---------------------------------------------------------------------------
# Tests                                                                       
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task(task_manager):
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg)
    assert task.status.state == TaskState.submitted

    # wait up to 1 s for completion
    for _ in range(10):
        await asyncio.sleep(0.1)
        if (await task_manager.get_task(task.id)).status.state == TaskState.completed:
            break
    assert (await task_manager.get_task(task.id)).status.state == TaskState.completed


@pytest.mark.asyncio
async def test_create_task_with_specific_handler(task_manager):
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg, handler_name="slow")

    states: List[TaskState] = []
    for _ in range(15):
        await asyncio.sleep(0.1)
        cur = (await task_manager.get_task(task.id)).status.state
        states.append(cur)
        if cur == TaskState.completed:
            break
    assert TaskState.working in states and TaskState.completed in states


@pytest.mark.asyncio
async def test_get_nonexistent_task(task_manager):
    with pytest.raises(TaskNotFound):
        await task_manager.get_task("does-not-exist")


@pytest.mark.asyncio
async def test_update_status_valid_transition(task_manager):
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg, handler_name="slow")

    # wait until handler enters *working*
    while (await task_manager.get_task(task.id)).status.state != TaskState.working:
        await asyncio.sleep(0.05)

    agent_msg = Message(role=Role.agent, parts=[TextPart(type="text", text="Info pls")])
    upd = await task_manager.update_status(task.id, TaskState.input_required, agent_msg)
    assert upd.status.state == TaskState.input_required

    user_msg2 = Message(role=Role.user, parts=[TextPart(type="text", text="More info")])
    upd2 = await task_manager.update_status(task.id, TaskState.working, user_msg2)
    assert upd2.status.state == TaskState.working


@pytest.mark.asyncio
async def test_update_status_invalid_transition(task_manager):
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="T")])
    task = await task_manager.create_task(user_msg)

    with pytest.raises(InvalidTransition):
        await task_manager.update_status(task.id, TaskState.input_required)


@pytest.mark.asyncio
async def test_add_artifact(task_manager):
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="T")])
    task = await task_manager.create_task(user_msg)

    artifact = Artifact(name="art", parts=[TextPart(type="text", text="data")], index=0)
    upd = await task_manager.add_artifact(task.id, artifact)
    assert upd.artifacts and upd.artifacts[0].name == "art"


@pytest.mark.asyncio
async def test_cancel_task(task_manager):
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="T")])
    task = await task_manager.create_task(user_msg, handler_name="cancellable")
    await asyncio.sleep(0.1)
    canceled = await task_manager.cancel_task(task.id, reason="cancel")
    assert canceled.status.state == TaskState.canceled


@pytest.mark.asyncio
async def test_tasks_by_state(task_manager):
    msg1 = Message(role=Role.user, parts=[TextPart(type="text", text="A")])
    task1 = await task_manager.create_task(msg1, handler_name="simple")

    msg2 = Message(role=Role.user, parts=[TextPart(type="text", text="B")])
    task2 = await task_manager.create_task(msg2, handler_name="slow")

    await asyncio.sleep(0.2)
    assert any(t.id == task2.id for t in task_manager.tasks_by_state(TaskState.working))

    await asyncio.sleep(0.6)
    completed = task_manager.tasks_by_state(TaskState.completed)
    ids = {t.id for t in completed}
    assert {task1.id, task2.id}.issubset(ids)


@pytest.mark.asyncio
async def test_event_publishing(event_bus, task_manager):
    q = event_bus.subscribe()
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="ECHO")])
    _ = await task_manager.create_task(user_msg, handler_name="echo")

    events = []
    try:
        for _ in range(40):
            try:
                evt = await asyncio.wait_for(q.get(), 0.05)
                events.append(evt)
                if getattr(evt, "final", False):
                    break
            except asyncio.TimeoutError:
                pass
    finally:
        event_bus.unsubscribe(q)

    assert any(isinstance(e, TaskStatusUpdateEvent) for e in events)
    assert any(isinstance(e, TaskArtifactUpdateEvent) for e in events)
