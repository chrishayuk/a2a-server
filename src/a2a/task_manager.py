from __future__ import annotations

"""
Task Manager – In‑memory FSM for the A2A Protocol (Pydantic v2 edition)
-----------------------------------------------------------------------

This implementation works directly with TextPart, FilePart, and DataPart 
instead of trying to use the problematic union type Part.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
from uuid import uuid4
import asyncio
import warnings

from a2a.models.spec import (
    Artifact,
    Message,
    # Skip Part for now until it's fixed
    # Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
    # Add other part types if needed
    # DataPart, 
    # FilePart,
)

__all__ = ["TaskManager", "TaskNotFound", "InvalidTransition"]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TaskNotFound(Exception):
    """Raised when a task ID is not present in the manager."""


class InvalidTransition(Exception):
    """Raised on an illegal state transition according to the FSM."""


# ---------------------------------------------------------------------------
# Task Manager
# ---------------------------------------------------------------------------


class TaskManager:
    """Minimal in‑memory implementation of the A2A task lifecycle."""

    _valid_transitions: Dict[TaskState, List[TaskState]] = {
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

    def __init__(self) -> None:
        self._tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    async def create_task(self, user_msg: Message, session_id: Optional[str] = None) -> Task:
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
        message: Optional[Message] = None,
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
            if message is not None:
                task.history = (task.history or []) + [message]
            return task

    async def add_artifact(self, task_id: str, artifact: Artifact) -> Task:
        async with self._lock:
            task = await self.get_task(task_id)
            task.artifacts = (task.artifacts or []) + [artifact]
            return task

    async def cancel_task(self, task_id: str, reason: str | None = None) -> Task:
        cancel_part = TextPart(type="text", text=reason or "Canceled by client")
        cancel_msg = Message(role=Role.agent, parts=[cancel_part])
        return await self.update_status(task_id, TaskState.canceled, cancel_msg)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def tasks_by_state(self, state: TaskState) -> List[Task]:
        return [t for t in self._tasks.values() if t.status.state == state]


# ---------------------------------------------------------------------------
# Smoke‑test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Silence Pydantic serializer warnings in the demo
    warnings.filterwarnings(
        "ignore",
        message="Pydantic serializer warnings:",
        category=UserWarning
    )

    async def _demo() -> None:
        tm = TaskManager()
        user_part = TextPart(type="text", text="Tell me a joke")
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
