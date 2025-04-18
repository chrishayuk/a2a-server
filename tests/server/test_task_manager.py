# File: a2a/server/task_manager.py

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
    ...

class InvalidTransition(Exception):
    ...


class TaskManager:
    """Minimal in‑memory implementation of the A2A task lifecycle, with optional event publishing."""

    _valid_transitions = {
        TaskState.submitted: [TaskState.working, TaskState.completed, TaskState.canceled, TaskState.failed],
        TaskState.working:   [TaskState.input_required, TaskState.completed, TaskState.canceled, TaskState.failed],
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
                session_id=sess_id,
                status=TaskStatus(state=TaskState.submitted),
                history=[user_msg],
            )
            self._tasks[task_id] = task

        # publish the new‑task status event
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
                message=message,
                timestamp=datetime.now(timezone.utc),
            )
            if message:
                task.history = task.history + [message]

        # publish the status update (final if terminal state)
        if self._event_bus:
            final = new_state in (TaskState.completed, TaskState.canceled, TaskState.failed)
            await self._event_bus.publish(
                TaskStatusUpdateEvent(id=task.id, status=task.status, final=final)
            )
        return task

    async def add_artifact(self, task_id: str, artifact: Artifact) -> Task:
        async with self._lock:
            task = await self.get_task(task_id)
            task.artifacts = (task.artifacts or []) + [artifact]

        # publish the artifact event
        if self._event_bus:
            await self._event_bus.publish(
                TaskArtifactUpdateEvent(id=task.id, artifact=artifact)
            )
        return task

    async def cancel_task(self, task_id: str, reason: str | None = None) -> Task:
        from a2a.models.spec import TextPart, Message, Role
        cancel_part = TextPart(type="text", text=reason or "Canceled by client")
        cancel_msg = Message(role=Role.agent, parts=[cancel_part])
        return await self.update_status(task_id, TaskState.canceled, cancel_msg)

    def tasks_by_state(self, state: TaskState) -> list[Task]:
        return [t for t in self._tasks.values() if t.status.state == state]
