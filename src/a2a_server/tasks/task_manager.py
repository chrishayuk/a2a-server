"""
a2a_server.tasks.task_manager
================================
Canonical TaskManager used by all transports.

Key guarantees
--------------
* Accepts **`task_id`** or **`id`** kwarg so transports never need to guess.
* Keeps an **alias map** so both server‑generated and client‑provided IDs work.
* Publishes initial *submitted* status immediately via `EventBus`.
* Provides **legacy helpers** `get_handler`, `get_handlers`, `get_default_handler`.
* Exposes the historical names `_tasks` and `_active_tasks` so older code that
  pokes internals continues to run.
* Graceful `shutdown()` cancels and waits for background jobs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from a2a_json_rpc.spec import (
    Artifact,
    Message,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_handler import TaskHandler

__all__ = [
    "TaskManager",
    "TaskNotFound",
    "InvalidTransition",
]

logger = logging.getLogger(__name__)


class TaskNotFound(Exception):
    """Raised when the requested task ID is unknown."""


class InvalidTransition(Exception):
    """Raised on an illegal FSM transition."""


class TaskManager:  # pylint: disable=too-many-instance-attributes
    """Central task registry and orchestrator for the A2A server."""

    _TRANSITIONS: Dict[TaskState, List[TaskState]] = {
        TaskState.submitted:     [TaskState.working, TaskState.completed, TaskState.canceled, TaskState.failed],
        TaskState.working:       [TaskState.input_required, TaskState.completed, TaskState.canceled, TaskState.failed],
        TaskState.input_required:[TaskState.working, TaskState.canceled],
        TaskState.completed:     [],
        TaskState.canceled:      [],
        TaskState.failed:        [],
        TaskState.unknown:       list(TaskState),
    }

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._bus = event_bus
        self._tasks: Dict[str, Task] = {}
        self._aliases: Dict[str, str] = {}           # alias → canonical
        self._handlers: Dict[str, TaskHandler] = {}
        self._default_handler: str | None = None
        self._active: Dict[str, str] = {}            # task_id → handler_name
        self._active_tasks: Dict[str, str] = self._active  # legacy alias

        self._lock = asyncio.Lock()
        self._background: set[asyncio.Task[Any]] = set()

    # ─── handler registry ───────────────────────────────────────────────

    def register_handler(self, handler: TaskHandler, *, default: bool = False) -> None:
        self._handlers[handler.name] = handler
        if default or self._default_handler is None:
            self._default_handler = handler.name
        logger.debug("Registered handler %s%s", handler.name, " (default)" if default else "")

    def _resolve_handler(self, name: str | None) -> TaskHandler:
        if name is None:
            if self._default_handler is None:
                raise ValueError("No default handler registered")
            return self._handlers[self._default_handler]
        return self._handlers[name]

    def get_handler(self, name: str | None = None) -> TaskHandler:
        return self._resolve_handler(name)

    def get_handlers(self) -> Dict[str, str]:
        return {n: n for n in self._handlers}

    def get_default_handler(self) -> str | None:
        return self._default_handler

    # ─── public API ────────────────────────────────────────────────────

    async def create_task(
        self,
        user_msg: Message,
        *,
        session_id: str | None = None,
        handler_name: str | None = None,
        task_id: str | None = None,
        id: str | None = None,
    ) -> Task:
        """
        Register *user_msg* as a new task.

        You may pass either `task_id=…` or `id=…`; whichever you provide
        becomes the client‑visible ID.  Internally we normalize to `canonical`.
        """
        canonical = id or task_id or str(uuid4())

        async with self._lock:
            if canonical in self._tasks:
                raise ValueError(f"Task {canonical} already exists")

            if id and task_id and id != task_id:
                self._aliases[id] = canonical

            task = Task(
                id=canonical,
                session_id=session_id or str(uuid4()),
                status=TaskStatus(state=TaskState.submitted),
                history=[user_msg],
            )
            self._tasks[canonical] = task
            hdl = self._resolve_handler(handler_name)
            self._active[canonical] = hdl.name

        if self._bus:
            await self._bus.publish(
                TaskStatusUpdateEvent(id=canonical, status=task.status, final=False)
            )

        bg = asyncio.create_task(self._run_task(canonical, hdl, user_msg, task.session_id))
        self._background.add(bg)
        bg.add_done_callback(self._background.discard)

        return task

    async def get_task(self, task_id: str) -> Task:
        real = self._aliases.get(task_id, task_id)
        try:
            return self._tasks[real]
        except KeyError as exc:
            raise TaskNotFound(task_id) from exc

    async def update_status(
        self,
        task_id: str,
        new_state: TaskState,
        message: Message | None = None,
    ) -> Task:
        real = self._aliases.get(task_id, task_id)
        async with self._lock:
            task = await self.get_task(real)
            cur = task.status.state
            if new_state != cur and new_state not in self._TRANSITIONS[cur]:
                raise InvalidTransition(f"{cur} → {new_state} not allowed")
            task.status = TaskStatus(state=new_state, timestamp=datetime.now(timezone.utc))
            if message:
                task.history = (task.history or []) + [message]

        if self._bus:
            await self._bus.publish(
                TaskStatusUpdateEvent(
                    id=real,
                    status=task.status,
                    final=new_state in (TaskState.completed, TaskState.canceled, TaskState.failed),
                )
            )
        return task

    async def add_artifact(self, task_id: str, artifact: Artifact) -> Task:
        real = self._aliases.get(task_id, task_id)
        async with self._lock:
            task = await self.get_task(real)
            task.artifacts = (task.artifacts or []) + [artifact]
        if self._bus:
            await self._bus.publish(TaskArtifactUpdateEvent(id=real, artifact=artifact))
        return task

    async def cancel_task(self, task_id: str, *, reason: str | None = None) -> Task:
        real = self._aliases.get(task_id, task_id)
        h_name = self._active.get(real)
        if h_name and await self._handlers[h_name].cancel_task(real):
            return await self._finish_cancel(real, reason)
        return await self._finish_cancel(real, reason)

    async def _finish_cancel(self, task_id: str, reason: str | None) -> Task:
        msg = Message(role=Role.agent, parts=[TextPart(type="text", text=reason or "Canceled by client")])
        return await self.update_status(task_id, TaskState.canceled, message=msg)

    async def _run_task(self, task_id: str, handler: TaskHandler, user_msg: Message, session_id: str) -> None:
        try:
            async for event in handler.process_task(task_id, user_msg, session_id):
                if isinstance(event, TaskStatusUpdateEvent):
                    await self.update_status(task_id, event.status.state, message=event.status.message)
                elif isinstance(event, TaskArtifactUpdateEvent):
                    await self.add_artifact(task_id, event.artifact)
        except asyncio.CancelledError:
            logger.info("Task %s cancelled", task_id)
            await self.update_status(task_id, TaskState.canceled)
            raise
        except Exception as exc:
            logger.exception("Task %s failed: %s", task_id, exc)
            await self.update_status(task_id, TaskState.failed)
        finally:
            self._active.pop(task_id, None)

    async def shutdown(self) -> None:
        for bg in list(self._background):
            bg.cancel()
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)
        self._background.clear()

    def tasks_by_state(self, state: TaskState) -> List[Task]:
        """Return all tasks currently in the given state."""
        return [t for t in self._tasks.values() if t.status.state == state]