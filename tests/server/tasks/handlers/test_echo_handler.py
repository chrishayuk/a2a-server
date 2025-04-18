# File: tests/server/tasks/handlers/test_echo_handler.py

import asyncio
import pytest

from a2a.server.tasks.handlers.echo_handler import EchoHandler
from a2a.json_rpc.spec import (
    Message, TextPart, TaskStatusUpdateEvent, TaskArtifactUpdateEvent,
    TaskState
)

@pytest.mark.asyncio
async def test_echo_handler_name():
    """Test that the echo handler has the expected name."""
    handler = EchoHandler()
    assert handler.name == "echo"

@pytest.mark.asyncio
async def test_echo_handler_supported_content_types():
    """Test that the echo handler supports text/plain content type."""
    handler = EchoHandler()
    assert "text/plain" in handler.supported_content_types

@pytest.mark.asyncio
async def test_echo_handler_process_task():
    """Test that the echo handler processes a task correctly."""
    handler = EchoHandler()
    
    # Create a test message
    text_part = TextPart(type="text", text="Hello, world!")
    message = Message(role="user", parts=[text_part])
    
    # Process the task
    task_id = "test-task-id"
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Check that we get the expected events
    assert len(events) == 3
    
    # First event should be a status update to "working"
    assert isinstance(events[0], TaskStatusUpdateEvent)
    assert events[0].id == task_id
    assert events[0].status.state == TaskState.working
    assert events[0].final is False
    
    # Second event should be an artifact with the echoed message
    assert isinstance(events[1], TaskArtifactUpdateEvent)
    assert events[1].id == task_id
    assert events[1].artifact.name == "echo"
    assert len(events[1].artifact.parts) == 1
    
    # Access text properties through model_dump()
    part_data = events[1].artifact.parts[0].model_dump()
    assert part_data["type"] == "text"
    assert part_data["text"] == "Echo: Hello, world!"
    
    # Third event should be a status update to "completed"
    assert isinstance(events[2], TaskStatusUpdateEvent)
    assert events[2].id == task_id
    assert events[2].status.state == TaskState.completed
    assert events[2].final is True

@pytest.mark.asyncio
async def test_echo_handler_with_empty_message():
    """Test that the echo handler handles empty messages correctly."""
    handler = EchoHandler()
    
    # Create an empty message
    message = Message(role="user", parts=[])
    
    # Process the task
    task_id = "test-task-id"
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Check that we still get the expected events
    assert len(events) == 3
    
    # Check the artifact content
    assert isinstance(events[1], TaskArtifactUpdateEvent)
    part_data = events[1].artifact.parts[0].model_dump()
    assert part_data["text"] == "Echo: "

@pytest.mark.asyncio
async def test_echo_handler_with_non_text_part():
    """Test that the echo handler handles non-text parts correctly."""
    handler = EchoHandler()
    
    # Create a message with a non-text part
    part = {"type": "data", "data": {"key": "value"}}
    message = Message(role="user", parts=[part])
    
    # Process the task
    task_id = "test-task-id"
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Check that we still get the expected events
    assert len(events) == 3
    
    # Check the artifact content - should extract empty text
    assert isinstance(events[1], TaskArtifactUpdateEvent)
    part_data = events[1].artifact.parts[0].model_dump()
    assert part_data["text"] == "Echo: "

@pytest.mark.asyncio
async def test_echo_handler_cancel_task():
    """Test that the echo handler's cancel_task method returns False."""
    handler = EchoHandler()
    assert await handler.cancel_task("test-task-id") is False

@pytest.mark.asyncio
async def test_echo_handler_cancellation():
    """Test that the echo handler can be cancelled."""
    handler = EchoHandler()
    
    # Create a test message
    text_part = TextPart(type="text", text="Hello, world!")
    message = Message(role="user", parts=[text_part])
    
    # Start processing the task
    task_id = "test-task-id"
    process_task = handler.process_task(task_id, message)
    
    # Create a task to consume events for a short time then cancel
    async def consume_and_cancel():
        count = 0
        try:
            async for _ in process_task:
                count += 1
                if count >= 1:  # Cancel after receiving the first event
                    # Cancel the task (this cancels the async iterator)
                    return count
        except asyncio.CancelledError:
            pass
    
    # Run the consumer task with a timeout
    consume_task = asyncio.create_task(consume_and_cancel())
    
    # Wait for the task with a timeout
    try:
        result = await asyncio.wait_for(consume_task, timeout=2.0)
        assert result >= 1  # We should have received at least one event
    except asyncio.TimeoutError:
        # Cancel the task if it's taking too long
        consume_task.cancel()
        await asyncio.gather(consume_task, return_exceptions=True)
        pytest.fail("Echo handler did not respond in time")