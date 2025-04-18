# File: src/a2a/server/task_manager.py

import asyncio
from datetime import datetime, timezone
from uuid import uuid4
import logging

from a2a.json_rpc.spec import (
    Message,
    Artifact,
    Task,
    TaskStatus,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    Role,
    TextPart,
)
from a2a.server.pubsub import EventBus
from a2a.server.tasks.task_handler_registry import TaskHandlerRegistry

logger = logging.getLogger(__name__)

class TaskNotFound(Exception):
    """Raised when a task ID is not present in the manager."""

class InvalidTransition(Exception):
    """Raised on an illegal state transition according to the FSM."""

class TaskManager:
    """
    Manages A2A tasks and delegates processing to registered handlers.
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
        # Add valid transitions from canceled and failed states to avoid errors
        TaskState.canceled: [TaskState.canceled],
        TaskState.failed: [TaskState.failed],
    }

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._event_bus = event_bus
        self._handler_registry = TaskHandlerRegistry()
        self._active_tasks = {}  # Map of task_id -> handler name
        # Keep track of active background tasks
        self._background_tasks = set()

    def register_handler(self, handler, default: bool = False) -> None:
        """Register a task handler with this manager."""
        self._handler_registry.register(handler, default)

    def _register_task(self, task):
        """Register a background task for cleanup."""
        self._background_tasks.add(task)
        
        # Set up removal when the task is done
        def _clean_task(t):
            self._background_tasks.discard(t)
        task.add_done_callback(_clean_task)
        
        return task

    async def create_task(
        self, 
        user_msg: Message, 
        session_id: str | None = None,
        handler_name: str | None = None
    ) -> Task:
        """Create a task and select appropriate handler."""
        async with self._lock:
            task_id = str(uuid4())
            sess_id = session_id or str(uuid4())
            task = Task(
                id=task_id,
                session_id=sess_id,  # Use snake_case as defined in the model
                status=TaskStatus(state=TaskState.submitted),
                history=[user_msg],
            )
            self._tasks[task_id] = task
            
            # Select handler and remember which one we used
            handler = self._handler_registry.get(handler_name)
            self._active_tasks[task_id] = handler.name

        if self._event_bus:
            await self._event_bus.publish(
                TaskStatusUpdateEvent(id=task.id, status=task.status, final=False)
            )
        
        # Launch the task processing in the background
        background_task = asyncio.create_task(
            self._process_task(task_id, handler, user_msg, sess_id)
        )
        self._register_task(background_task)
        
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
            
            # Skip validation if transitioning to the same state
            if task.status.state != new_state and new_state not in self._valid_transitions.get(task.status.state, []):
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
        # Try to cancel via the handler first
        handler_name = self._active_tasks.get(task_id)
        if handler_name:
            handler = self._handler_registry.get(handler_name)
            success = await handler.cancel_task(task_id)
            if success:
                # Create a cancellation message
                cancel_part = TextPart(type="text", text=reason or "Canceled by client")
                cancel_msg = Message(role=Role.agent, parts=[cancel_part])
                # Make sure the message gets added to history
                return await self.update_status(task_id, TaskState.canceled, cancel_msg)
        
        # Otherwise just mark it as canceled
        cancel_part = TextPart(type="text", text=reason or "Canceled by client")
        cancel_msg = Message(role=Role.agent, parts=[cancel_part])
        return await self.update_status(task_id, TaskState.canceled, cancel_msg)

    def tasks_by_state(self, state: TaskState) -> list[Task]:
        return [t for t in self._tasks.values() if t.status.state == state]
        
    async def _process_task(
        self, 
        task_id: str, 
        handler,
        message: Message,
        session_id: str | None
    ) -> None:
        """Process a task by delegating to the selected handler."""
        try:
            async for event in handler.process_task(task_id, message, session_id):
                # Update our task record based on events
                if isinstance(event, TaskStatusUpdateEvent):
                    await self.update_status(
                        task_id, 
                        event.status.state, 
                        event.status.message
                    )
                elif isinstance(event, TaskArtifactUpdateEvent):
                    await self.add_artifact(task_id, event.artifact)
                    
                # Events are also published via update_status/add_artifact
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            logger.info(f"Task {task_id} processing was cancelled")
            
            # Only update if not already canceled
            task = await self.get_task(task_id)
            if task.status.state != TaskState.canceled:
                await self.update_status(task_id, TaskState.canceled)
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskStatusUpdateEvent(
                            id=task_id, 
                            status=TaskStatus(state=TaskState.canceled),
                            final=True
                        )
                    )
            raise  # Re-raise so asyncio sees task was properly cancelled
        except Exception as e:
            # Update task to failed state on error
            logger.exception(f"Error in handler for task {task_id}: {e}")
            
            # Only update if not already in terminal state
            task = await self.get_task(task_id)
            if task.status.state not in (TaskState.completed, TaskState.canceled, TaskState.failed):
                await self.update_status(task_id, TaskState.failed)
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskStatusUpdateEvent(
                            id=task_id, 
                            status=TaskStatus(state=TaskState.failed),
                            final=True
                        )
                    )
        finally:
            # Clean up
            if task_id in self._active_tasks:
                del self._active_tasks[task_id]


async def cancel_pending_tasks():
    """Cancel all pending background tasks and wait for them to complete."""
    from a2a.server.methods import _background_tasks
    
    tasks = list(_background_tasks)
    for task in tasks:
        if not task.done():
            task.cancel()
    
    if tasks:
        # Wait for all tasks to complete cancellation
        await asyncio.gather(*tasks, return_exceptions=True)
    
    _background_tasks.clear()