# File: src/a2a/server/task_manager.py
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from a2a.models.spec import (
    Message,
    Artifact,
    Task,
    TaskStatus,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)
from a2a.server.pubsub import EventBus


class TaskNotFound(Exception):
    """Raised when a task ID is not present in the manager."""


class InvalidTransition(Exception):
    """Raised on an illegal state transition according to the FSM."""


class TaskManager:
    """
    Minimal in‑memory implementation of the A2A task lifecycle,
    with optional event publishing via EventBus.
    """

    _valid_transitions: dict[TaskState, list[TaskState]] = {
        TaskState.submitted: [
            TaskState.working,
            TaskState.completed,
            TaskState.canceled,
            TaskState.failed,
        ],
        TaskState.working: [
            TaskState.input_required,
            TaskState.completed,
            TaskState.canceled,
            TaskState.failed,
        ],
        TaskState.input_required: [TaskState.working, TaskState.canceled],
    }

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._event_bus = event_bus

    async def create_task(self, user_msg: Message, session_id: str | None = None) -> Task:
        async with self._lock:
            task_id = str(uuid4())
            sess_id = session_id or str(uuid4())
            task = Task(
                id=task_id,
                sessionId=sess_id,
                status=TaskStatus(state=TaskState.submitted),
                history=[user_msg],
            )
            self._tasks[task_id] = task

        if self._event_bus:
            await self._event_bus.publish(
                TaskStatusUpdateEvent(id=task.id, status=task.status, final=False)
            )
        return task

    async def get_task(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        return task

    async def update_status(
        self,
        task_id: str,
        new_state: TaskState,
        message: Message | None = None,
    ) -> Task:
        async with self._lock:
            task = await self.get_task(task_id)
            if new_state not in self._valid_transitions.get(task.status.state, []):
                raise InvalidTransition(f"{task.status.state} → {new_state} not allowed")

            task.status = TaskStatus(
                state=new_state,
                timestamp=datetime.now(timezone.utc),
            )
            if message is not None:
                # record message in history but not in TaskStatus
                task.history = (task.history or []) + [message]

        if self._event_bus:
            final = new_state in (
                TaskState.completed,
                TaskState.canceled,
                TaskState.failed,
            )
            await self._event_bus.publish(
                TaskStatusUpdateEvent(id=task.id, status=task.status, final=final)
            )
        return task

    async def add_artifact(self, task_id: str, artifact: Artifact) -> Task:
        async with self._lock:
            task = await self.get_task(task_id)
            task.artifacts = (task.artifacts or []) + [artifact]

        if self._event_bus:
            await self._event_bus.publish(
                TaskArtifactUpdateEvent(id=task.id, artifact=artifact)
            )
        return task

    async def cancel_task(self, task_id: str, reason: str | None = None) -> Task:
        # Cancel without embedding a message into TaskStatus
        return await self.update_status(task_id, TaskState.canceled)

    def tasks_by_state(self, state: TaskState) -> list[Task]:
        return [t for t in self._tasks.values() if t.status.state == state]


if __name__ == "__main__":
    import warnings
    from a2a.models.spec import TextPart, Role

    warnings.filterwarnings(
        "ignore",
        message="Pydantic serializer warnings:",
        category=UserWarning,
    )

    async def _demo():
        tm = TaskManager()
        user_part = TextPart(type="text", text="Tell me a joke")
        from a2a.models.spec import Message

        user_msg = Message(role=Role.user, parts=[user_part])
        task = await tm.create_task(user_msg)
        print("Created:\n", task.model_dump_json(indent=2))

        await tm.update_status(task.id, TaskState.working)
        joke_part = TextPart(type="text", text="Why did the chicken cross the road? …")
        artifact = Artifact(name="joke", parts=[joke_part], index=0)
        await tm.add_artifact(task.id, artifact)
        await tm.update_status(task.id, TaskState.completed)

        final = await tm.get_task(task.id)
        print("\nFinal:\n", final.model_dump_json(indent=2))

    asyncio.run(_demo())
