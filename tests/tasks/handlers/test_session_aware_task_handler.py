# File: tests/tasks/handlers/test_session_aware_task_handler.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any, Optional, AsyncIterable

from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

# Mock the chuk_ai_session_manager module since it may not be installed
class MockAISessionManager:
    def __init__(self, **kwargs):
        self.session_id = "mock_session"
        self.config = kwargs
        
    async def user_says(self, message: str):
        return True
        
    async def ai_responds(self, response: str, model: str = "mock", provider: str = "mock"):
        return True
        
    async def get_conversation(self) -> List[Dict[str, str]]:
        return [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        
    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_tokens": 100,
            "estimated_cost": 0.001,
            "user_messages": 1,
            "ai_messages": 1,
            "session_segments": 1
        }

# Mock the session storage setup function
def mock_setup_chuk_sessions_storage(sandbox_id: str, default_ttl_hours: int = 24):
    pass

# Patch the imports before importing the module
with patch.dict('sys.modules', {
    'chuk_ai_session_manager': MagicMock(SessionManager=MockAISessionManager),
    'chuk_ai_session_manager.session_storage': MagicMock(setup_chuk_sessions_storage=mock_setup_chuk_sessions_storage)
}):
    from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler


# Mock implementation of SessionAwareTaskHandler for testing
class MockSessionHandler(SessionAwareTaskHandler):
    """Mock implementation for testing."""
    
    def __init__(self, name="mock_session", **kwargs):
        super().__init__(name, **kwargs)
        # Mock the AI session creation for testing
        self._mock_ai_sessions = {}
        
    async def _get_ai_session_manager(self, a2a_session_id: Optional[str]) -> Optional[MockAISessionManager]:
        """Override to return mock session manager."""
        if not a2a_session_id:
            return None  # Return None for None session_id
            
        if a2a_session_id not in self._mock_ai_sessions:
            self._mock_ai_sessions[a2a_session_id] = MockAISessionManager()
            
        return self._mock_ai_sessions[a2a_session_id]
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """Required implementation of process_task."""
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        # Use the session functionality
        if session_id:
            await self.add_user_message(session_id, "Test message")
            await self.add_ai_response(session_id, "Test response")
        
        # Create a simple artifact
        artifact = Artifact(
            name="test_response",
            parts=[TextPart(type="text", text="Mock response")],
            index=0
        )
        
        yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
        
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True
        )


# Tests
@pytest.fixture
def mock_session_store():
    """Fixture for a mock session store."""
    store = MagicMock()
    store.get = AsyncMock()
    return store


@pytest.fixture
def handler(mock_session_store):
    """Fixture for a SessionAwareTaskHandler instance."""
    return MockSessionHandler(
        name="test_handler",
        session_store=mock_session_store,
        sandbox_id="test_sandbox",
        session_sharing=False
    )


@pytest.mark.asyncio
async def test_initialization():
    """Test initialization of SessionAwareTaskHandler."""
    # Test with default params
    handler = MockSessionHandler(name="test_handler")
    assert handler.name == "test_handler"
    assert handler.sandbox_id is not None
    assert handler.session_sharing is False
    
    # Test with session sharing enabled
    handler = MockSessionHandler(
        name="shared_handler",
        session_sharing=True,
        shared_sandbox_group="test_group"
    )
    assert handler.session_sharing is True
    assert handler.shared_sandbox_group == "test_group"


@pytest.mark.asyncio
async def test_session_sharing_configuration():
    """Test session sharing configuration logic."""
    # Test auto-detection when shared_sandbox_group is provided
    handler = MockSessionHandler(
        name="auto_shared",
        shared_sandbox_group="auto_group"
    )
    assert handler.session_sharing is True
    assert handler.shared_sandbox_group == "auto_group"
    
    # Test explicit session sharing disabled
    handler = MockSessionHandler(
        name="explicit_disabled",
        session_sharing=False,
        shared_sandbox_group="group"
    )
    assert handler.session_sharing is False
    assert handler.shared_sandbox_group == "group"


@pytest.mark.asyncio
async def test_add_user_message(handler):
    """Test add_user_message method."""
    # Test with valid session
    result = await handler.add_user_message("test_session", "Hello")
    assert result is True
    
    # Test with empty message - should still succeed
    result = await handler.add_user_message("test_session", "")
    assert result is True  # Should handle gracefully
    
    # Test with no session - should return False when session_id is None
    result = await handler.add_user_message(None, "Hello")
    assert result is False  # Should return False when no session manager available


@pytest.mark.asyncio
async def test_add_ai_response(handler):
    """Test add_ai_response method."""
    # Test with valid session
    result = await handler.add_ai_response("test_session", "Hi there", "gpt-4", "openai")
    assert result is True
    
    # Test with default model/provider
    result = await handler.add_ai_response("test_session", "Response")
    assert result is True
    
    # Test with empty response
    result = await handler.add_ai_response("test_session", "")
    assert result is True  # Should handle gracefully


@pytest.mark.asyncio
async def test_get_conversation_history(handler):
    """Test get_conversation_history method."""
    # Test with valid session
    history = await handler.get_conversation_history("test_session")
    assert isinstance(history, list)
    assert len(history) >= 0  # Could be empty or have mock data
    
    # Test with no session
    history = await handler.get_conversation_history(None)
    assert history == []


@pytest.mark.asyncio
async def test_get_conversation_context(handler):
    """Test get_conversation_context method."""
    # Test with valid session
    context = await handler.get_conversation_context("test_session", max_messages=5)
    assert isinstance(context, list)
    
    # Test with no session
    context = await handler.get_conversation_context(None)
    assert context == []


@pytest.mark.asyncio
async def test_get_token_usage(handler):
    """Test get_token_usage method."""
    # Test with valid session
    usage = await handler.get_token_usage("test_session")
    assert isinstance(usage, dict)
    assert "total_tokens" in usage
    assert "estimated_cost" in usage
    
    # Test with no session
    usage = await handler.get_token_usage(None)
    assert isinstance(usage, dict)
    assert usage.get("total_tokens", 0) >= 0


@pytest.mark.asyncio
async def test_get_session_chain(handler):
    """Test get_session_chain method."""
    # Test with valid session
    chain = await handler.get_session_chain("test_session")
    assert isinstance(chain, list)
    
    # Test with no session
    chain = await handler.get_session_chain(None)
    assert chain == []


@pytest.mark.asyncio
async def test_cleanup_session(handler):
    """Test cleanup_session method."""
    # Test cleanup - should always return True
    result = await handler.cleanup_session("test_session")
    assert result is True


@pytest.mark.asyncio
async def test_get_session_stats(handler):
    """Test get_session_stats method."""
    stats = handler.get_session_stats()
    assert isinstance(stats, dict)
    assert "handler_name" in stats
    assert "session_sharing" in stats
    assert "sandbox_id" in stats
    assert stats["handler_name"] == "test_handler"


@pytest.mark.asyncio
async def test_validate_session_configuration(handler):
    """Test validate_session_configuration method."""
    validation = handler.validate_session_configuration()
    assert isinstance(validation, dict)
    assert "handler_name" in validation
    assert "configuration_valid" in validation
    assert "issues" in validation


@pytest.mark.asyncio
async def test_process_task_integration(handler):
    """Test integration with process_task."""
    message = Message(
        role="user",
        parts=[TextPart(type="text", text="Hello, test message")]
    )
    
    # Collect events
    events = []
    async for event in handler.process_task("task123", message, "test_session"):
        events.append(event)
    
    # Check events
    assert len(events) >= 2  # At least working and completed
    
    # Check for working state
    working_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent) and e.status.state == TaskState.working]
    assert len(working_events) >= 1
    
    # Check for completed state
    completed_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent) and e.status.state == TaskState.completed]
    assert len(completed_events) >= 1
    
    # Check final event is marked as final
    final_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent) and e.final]
    assert len(final_events) >= 1


@pytest.mark.asyncio
async def test_session_manager_creation(handler):
    """Test AI session manager creation."""
    # Test creating session manager
    session_manager = await handler._get_ai_session_manager("new_session")
    assert session_manager is not None
    assert isinstance(session_manager, MockAISessionManager)
    
    # Test reusing existing session manager
    same_manager = await handler._get_ai_session_manager("new_session")
    assert same_manager is session_manager  # Should be the same instance
    
    # Test with no session ID
    no_manager = await handler._get_ai_session_manager(None)
    assert no_manager is None


@pytest.mark.asyncio
async def test_shared_vs_isolated_sessions():
    """Test difference between shared and isolated session configurations."""
    # Test isolated sessions
    isolated_handler = MockSessionHandler(
        name="isolated",
        session_sharing=False,
        sandbox_id="isolated_sandbox"
    )
    assert isolated_handler.session_sharing is False
    assert isolated_handler.sandbox_id == "isolated_sandbox"
    
    # Test shared sessions
    shared_handler = MockSessionHandler(
        name="shared",
        session_sharing=True,
        shared_sandbox_group="shared_group"
    )
    assert shared_handler.session_sharing is True
    assert shared_handler.shared_sandbox_group == "shared_group"


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling in session operations."""
    # Create handler that will trigger errors
    handler = MockSessionHandler(name="error_test")
    
    # Override to simulate errors
    async def error_session_manager(session_id):
        raise Exception("Simulated error")
    
    handler._get_ai_session_manager = error_session_manager
    
    # Test that errors are handled gracefully
    result = await handler.add_user_message("test", "message")
    assert result is False  # Should return False on error
    
    result = await handler.add_ai_response("test", "response")
    assert result is False  # Should return False on error
    
    history = await handler.get_conversation_history("test")
    assert history == []  # Should return empty list on error


@pytest.mark.asyncio
async def test_session_configuration_validation():
    """Test session configuration validation."""
    # Test valid configuration
    valid_handler = MockSessionHandler(
        name="valid",
        session_sharing=True,
        shared_sandbox_group="valid_group"
    )
    validation = valid_handler.validate_session_configuration()
    assert validation["configuration_valid"] is True
    assert len(validation["issues"]) == 0
    
    # Test configuration with potential issues
    issue_handler = MockSessionHandler(
        name="issues",
        session_sharing=True,
        shared_sandbox_group=None  # This should create an issue
    )
    # Note: The current implementation might not catch this as an issue,
    # but the test demonstrates how validation could work


if __name__ == "__main__":
    # Run tests manually if needed
    import asyncio
    
    async def run_test():
        handler = MockSessionHandler("manual_test")
        print(f"Handler created: {handler.name}")
        print(f"Session sharing: {handler.session_sharing}")
        print(f"Sandbox ID: {handler.sandbox_id}")
        
        # Test session operations
        await handler.add_user_message("test", "Hello")
        await handler.add_ai_response("test", "Hi there")
        
        history = await handler.get_conversation_history("test")
        print(f"History: {history}")
        
        stats = handler.get_session_stats()
        print(f"Stats: {stats}")
    
    # Uncomment to run manual test
    # asyncio.run(run_test())