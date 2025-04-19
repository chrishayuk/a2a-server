"""
Tests for the Google ADK handler.
"""
import pytest
import asyncio
from typing import Dict, Any, AsyncIterable, Optional, List

from a2a.server.tasks.handlers.google_adk_handler import GoogleADKHandler
from a2a.json_rpc.spec import (
    Message, TextPart, Role, TaskState
)


class MockGoogleADKAgent:
    """Mock Google ADK agent for testing."""
    
    SUPPORTED_CONTENT_TYPES = ["text/plain", "application/json"]
    
    def __init__(self):
        self.invoke_called = False
        self.stream_called = False
        self.last_query = None
        self.last_session_id = None
    
    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        """Mock synchronous invocation."""
        self.invoke_called = True
        self.last_query = query
        self.last_session_id = session_id
        
        if "error" in query.lower():
            raise ValueError("Simulated error")
        elif "missing" in query.lower():
            return "MISSING_INFO: Please provide more information"
        else:
            return "This is a test response"

    async def stream(self, query: str, session_id: Optional[str] = None) -> AsyncIterable[Dict[str, Any]]:
        """Mock streaming invocation."""
        self.stream_called = True
        self.last_query = query
        self.last_session_id = session_id
        
        # First yield an intermediate update
        yield {
            "updates": "Processing...",
            "is_task_complete": False
        }
        
        # Wait a bit
        await asyncio.sleep(0.1)
        
        # Check for error case
        if "error" in query.lower():
            raise ValueError("Simulated streaming error")
        
        # Final response depends on query
        if "json" in query.lower():
            # Return JSON data
            yield {
                "content": {"status": "success", "message": "This is a test"},
                "is_task_complete": True
            }
        elif "missing" in query.lower():
            # Return input required
            yield {
                "content": {
                    "response": {
                        "result": '{"missing": "information", "field": "date"}'
                    }
                },
                "is_task_complete": True
            }
        else:
            # Return text
            yield {
                "content": "This is a streaming test response",
                "is_task_complete": True
            }


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    return MockGoogleADKAgent()


@pytest.fixture
def handler(mock_agent):
    """Create a handler with the mock agent."""
    return GoogleADKHandler(mock_agent)


def test_handler_properties(handler, mock_agent):
    """Test basic handler properties."""
    assert handler.name == "google_adk"
    assert handler.supported_content_types == mock_agent.SUPPORTED_CONTENT_TYPES


def test_extract_text_query(handler):
    """Test text extraction from message."""
    message = Message(
        role=Role.user,
        parts=[TextPart(type="text", text="Test query")]
    )
    
    assert handler._extract_text_query(message) == "Test query"


def test_extract_text_query_no_text(handler):
    """Test extraction fails with no text parts."""
    message = Message(
        role=Role.user,
        parts=[]
    )
    
    with pytest.raises(ValueError):
        handler._extract_text_query(message)


@pytest.mark.asyncio
async def test_process_task_streaming(handler, mock_agent):
    """Test task processing with streaming mode."""
    task_id = "test-task-id"
    message = Message(
        role=Role.user,
        parts=[TextPart(type="text", text="Test streaming query")]
    )
    
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Verify the agent was called correctly
    assert mock_agent.stream_called is True
    assert mock_agent.last_query == "Test streaming query"
    
    # Check events
    assert len(events) == 3  # working, artifact, completed
    
    # Check final status
    final_event = events[-1]
    assert final_event.id == task_id
    assert final_event.status.state == TaskState.completed


@pytest.mark.asyncio
async def test_process_task_json_data(handler, mock_agent):
    """Test task processing with JSON data return."""
    task_id = "test-task-id"
    message = Message(
        role=Role.user,
        parts=[TextPart(type="text", text="Test json query")]
    )
    
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Check events
    assert len(events) == 3  # working, artifact, completed
    
    # Check artifact
    artifact_event = events[1]
    assert artifact_event.artifact.parts[0].type == "data"
    assert artifact_event.artifact.parts[0].data == {"status": "success", "message": "This is a test"}


@pytest.mark.asyncio
async def test_process_task_input_required(handler, mock_agent):
    """Test task processing resulting in input required state."""
    task_id = "test-task-id"
    message = Message(
        role=Role.user,
        parts=[TextPart(type="text", text="Test missing information")]
    )
    
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Check final status is input_required
    final_event = events[-1]
    assert final_event.status.state == TaskState.input_required


@pytest.mark.asyncio
async def test_process_task_error(handler, mock_agent):
    """Test task processing with an error."""
    task_id = "test-task-id"
    message = Message(
        role=Role.user,
        parts=[TextPart(type="text", text="Test error case")]
    )
    
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Check final status is failed
    final_event = events[-1]
    assert final_event.status.state == TaskState.failed
    assert "error" in final_event.status.message.parts[0].text.lower()


@pytest.mark.asyncio
async def test_process_task_fallback_to_sync(handler, mock_agent):
    """Test fallback to sync mode when stream is not available."""
    # Temporarily remove stream method to test sync fallback
    stream_method = mock_agent.stream
    mock_agent.stream = None
    
    task_id = "test-task-id"
    message = Message(
        role=Role.user,
        parts=[TextPart(type="text", text="Test sync fallback")]
    )
    
    events = []
    async for event in handler.process_task(task_id, message):
        events.append(event)
    
    # Verify the agent.invoke was called
    assert mock_agent.invoke_called is True
    assert mock_agent.last_query == "Test sync fallback"
    
    # Check events
    assert len(events) == 3  # working, artifact, completed
    
    # Restore the stream method
    mock_agent.stream = stream_method


@pytest.mark.asyncio
async def test_cancel_task(handler):
    """Test cancellation (which is not supported)."""
    result = await handler.cancel_task("test-task-id")
    assert result is False  # Cancellation not supported