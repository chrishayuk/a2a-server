# File: tests/server/test_task_manager.py

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

from a2a_json_rpc.spec import (
    Message, TextPart, Role, Task, TaskStatus, TaskState,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent, Artifact
)
from a2a_server.tasks.task_manager import TaskManager, TaskNotFound, InvalidTransition
from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_handler import TaskHandler
from a2a_server.tasks.handlers.echo_handler import EchoHandler


class SimpleHandler(TaskHandler):
    """Simple test handler that completes immediately."""
    
    @property
    def name(self) -> str:
        return "simple"
    
    async def process_task(self, task_id, message, session_id=None):
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True
        )


class SlowHandler(TaskHandler):
    """Handler that takes time to complete."""
    
    @property
    def name(self) -> str:
        return "slow"
    
    async def process_task(self, task_id, message, session_id=None):
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        await asyncio.sleep(0.5)
        
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True
        )
    
    async def cancel_task(self, task_id: str) -> bool:
        # This handler supports cancellation
        return True


class CancellableHandler(TaskHandler):
    """Handler that can be cancelled."""
    
    def __init__(self):
        self.cancelled = {}
    
    @property
    def name(self) -> str:
        return "cancellable"
    
    async def process_task(self, task_id, message, session_id=None):
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        # Loop until cancelled
        while not self.cancelled.get(task_id, False):
            await asyncio.sleep(0.1)
            
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.canceled),
            final=True
        )
    
    async def cancel_task(self, task_id: str) -> bool:
        self.cancelled[task_id] = True
        return True


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def task_manager(event_bus):
    manager = TaskManager(event_bus)
    # Register handlers for testing
    manager.register_handler(SimpleHandler(), default=True)
    manager.register_handler(SlowHandler())
    manager.register_handler(CancellableHandler())
    manager.register_handler(EchoHandler())
    return manager


@pytest.mark.asyncio
async def test_create_task(task_manager):
    """Test creating a task with the default handler."""
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg)
    
    assert task.id
    assert task.session_id  # Use snake_case as defined in model
    assert task.status.state == TaskState.submitted
    assert task.history == [user_msg]
    
    # Wait for it to complete
    await asyncio.sleep(0.2)
    
    # Fetch again to see the updated state
    task = await task_manager.get_task(task.id)
    assert task.status.state == TaskState.completed


@pytest.mark.asyncio
async def test_create_task_with_specific_handler(task_manager):
    """Test creating a task with a specific handler."""
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg, handler_name="slow")
    
    assert task.id
    assert task.status.state == TaskState.submitted
    
    # Wait for it to start working
    await asyncio.sleep(0.2)
    
    # Fetch again to see the updated state
    task = await task_manager.get_task(task.id)
    assert task.status.state == TaskState.working
    
    # Wait for it to complete
    await asyncio.sleep(0.5)
    
    # Fetch again to see the final state
    task = await task_manager.get_task(task.id)
    assert task.status.state == TaskState.completed


@pytest.mark.asyncio
async def test_get_nonexistent_task(task_manager):
    """Test getting a nonexistent task raises TaskNotFound."""
    with pytest.raises(TaskNotFound):
        await task_manager.get_task("nonexistent-id")


@pytest.mark.asyncio
async def test_update_status_valid_transition(task_manager):
    """Test updating task status with valid state transitions."""
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg, handler_name="slow")
    
    # Wait for it to start working
    await asyncio.sleep(0.2)
    
    # Update to input_required (valid from working)
    agent_msg = Message(role=Role.agent, parts=[TextPart(type="text", text="Need more info")])
    updated = await task_manager.update_status(task.id, TaskState.input_required, agent_msg)
    
    assert updated.status.state == TaskState.input_required
    assert len(updated.history) == 2  # Original + agent message
    
    # Update back to working
    user_response = Message(role=Role.user, parts=[TextPart(type="text", text="More info")])
    updated = await task_manager.update_status(task.id, TaskState.working, user_response)
    
    assert updated.status.state == TaskState.working
    assert len(updated.history) == 3  # Original + agent + user


@pytest.mark.asyncio
async def test_update_status_invalid_transition(task_manager):
    """Test that invalid state transitions raise InvalidTransition."""
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg)
    
    # Invalid: submitted -> input_required
    with pytest.raises(InvalidTransition):
        await task_manager.update_status(task.id, TaskState.input_required)


@pytest.mark.asyncio
async def test_add_artifact(task_manager):
    """Test adding an artifact to a task."""
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg)
    
    # Add an artifact
    artifact = Artifact(
        name="test-artifact",
        parts=[TextPart(type="text", text="Artifact content")],
        index=0
    )
    updated = await task_manager.add_artifact(task.id, artifact)
    
    assert updated.artifacts
    assert len(updated.artifacts) == 1
    assert updated.artifacts[0].name == "test-artifact"
    
    # Access Part properties using model_dump
    part_data = updated.artifacts[0].parts[0].model_dump()
    assert part_data["text"] == "Artifact content"


@pytest.mark.asyncio
async def test_cancel_task(task_manager):
    """Test cancelling a task."""
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg, handler_name="cancellable")
    
    # Wait for it to start working
    await asyncio.sleep(0.2)
    
    # Cancel the task
    canceled = await task_manager.cancel_task(task.id, reason="Testing cancellation")
    
    assert canceled.status.state == TaskState.canceled
    
    # Verify the cancel message was added
    assert len(canceled.history) >= 2  # Original + cancellation
    
    # Check cancellation message text using model_dump for the second message
    cancel_msg_parts = canceled.history[1].parts[0].model_dump()
    assert "Testing cancellation" in cancel_msg_parts["text"]


@pytest.mark.asyncio
async def test_tasks_by_state(task_manager):
    """Test filtering tasks by state."""
    # Create tasks in different states
    msg1 = Message(role=Role.user, parts=[TextPart(type="text", text="Task 1")])
    task1 = await task_manager.create_task(msg1, handler_name="simple")
    
    msg2 = Message(role=Role.user, parts=[TextPart(type="text", text="Task 2")])
    task2 = await task_manager.create_task(msg2, handler_name="slow")
    
    # Wait for tasks to process
    await asyncio.sleep(0.2)
    
    # task1 should be completed, task2 should be working
    completed = task_manager.tasks_by_state(TaskState.completed)
    working = task_manager.tasks_by_state(TaskState.working)
    
    assert any(t.id == task1.id for t in completed)
    assert any(t.id == task2.id for t in working)
    
    # Wait for task2 to complete
    await asyncio.sleep(0.5)
    
    # Now both should be completed
    completed = task_manager.tasks_by_state(TaskState.completed)
    assert len(completed) >= 2
    assert any(t.id == task1.id for t in completed)
    assert any(t.id == task2.id for t in completed)

@pytest.mark.asyncio
async def test_event_publishing(event_bus, task_manager):
    """Test that events are published to the event bus."""
    # Create a mock queue to capture events
    event_queue = event_bus.subscribe()
    
    # Create a task
    user_msg = Message(role=Role.user, parts=[TextPart(type="text", text="Test")])
    task = await task_manager.create_task(user_msg, handler_name="echo")
    
    # Wait for the echo handler to start processing
    # Echo handler sleeps for 1 second, so we need to wait at least that long
    await asyncio.sleep(1.2)
    
    # Process events
    events = []
    try:
        # Collect events for up to 5 seconds to ensure we get everything
        for _ in range(20):  # Try up to 20 times
            try:
                # Short timeout for each attempt
                event = await asyncio.wait_for(event_queue.get(), 0.25)
                events.append(event)
                
                # If we got a final event, we can stop collecting
                if hasattr(event, 'final') and event.final:
                    break
            except asyncio.TimeoutError:
                # Break if we waited too long without getting a new event
                # This likely means all events have been published
                break
    finally:
        event_bus.unsubscribe(event_queue)
    
    # Verify we got events
    assert len(events) >= 3  # At least: submitted, working, artifact, completed
    
    # Check for specific event types
    status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
    artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
    
    assert len(status_events) >= 2  # At least: submitted, completed
    assert len(artifact_events) >= 1  # At least one artifact
    
    # Check that the artifact contains our echo text (using string representation)
    artifact_data_str = str(artifact_events)
    assert "Echo: Test" in artifact_data_str
    
    # Check that we got a final event
    assert any(e.final for e in status_events)
    