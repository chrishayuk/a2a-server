# File: tests/tasks/handlers/test_session_aware_task_handler.py
import pytest
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any, Optional, AsyncIterable

from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

# Create Mock classes for all chuk_session_manager dependencies
class MockEventSource:
    USER = "user"  # lowercase to match the actual implementation
    LLM = "llm"    # lowercase to match the actual implementation

class MockEventType:
    MESSAGE = "message"
    SUMMARY = "summary"
    TOOL_CALL = "tool_call"

# Creating a non-coroutine version of Session with create method
class MockSession:
    @staticmethod
    def create():
        """
        Non-async version of create - this is the key to fixing the warnings.
        We return a function that returns a future that's already done, so it can
        be used in an await expression without warnings.
        """
        session = MagicMock()
        session.id = "new_agent_session"
        future = asyncio.Future()
        future.set_result(session)
        return future

class MockSessionEvent:
    pass

class MockSummarizationStrategy:
    BASIC = "basic"
    KEY_POINTS = "key_points"
    QUERY_FOCUSED = "query_focused"
    TOPIC_BASED = "topic_based"

class MockInfiniteConversationManager:
    def __init__(self, token_threshold=4000, summarization_strategy="key_points"):
        self.token_threshold = token_threshold
        self.summarization_strategy = summarization_strategy
        self.process_message = AsyncMock()
        self.build_context_for_llm = AsyncMock(return_value=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"}
        ])
        self.get_full_conversation_history = AsyncMock(return_value=[
            ("user", "USER", "Hello"),
            ("assistant", "LLM", "Hi there"),
            ("user", "USER", "How are you?")
        ])

class MockSessionStoreProvider:
    _store = None
    
    @staticmethod
    def set_store(store):
        MockSessionStoreProvider._store = store
    
    @staticmethod
    def get_store():
        return MockSessionStoreProvider._store

# Create a dictionary of mocks for patching
mock_modules = {
    'chuk_session_manager.models.event_source': MagicMock(EventSource=MockEventSource),
    'chuk_session_manager.models.event_type': MagicMock(EventType=MockEventType),
    'chuk_session_manager.models.session': MagicMock(
        Session=MockSession,
        SessionEvent=MockSessionEvent
    ),
    'chuk_session_manager.storage': MagicMock(SessionStoreProvider=MockSessionStoreProvider),
    'chuk_session_manager.infinite_conversation': MagicMock(
        InfiniteConversationManager=MockInfiniteConversationManager,
        SummarizationStrategy=MockSummarizationStrategy
    ),
}

# Patch all the modules
with patch.dict('sys.modules', mock_modules):
    # Force SESSIONS_AVAILABLE to be True for tests
    with patch('a2a_server.tasks.handlers.session_aware_task_handler.SESSIONS_AVAILABLE', True):
        from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler


# Mock implementation of SessionAwareTaskHandler for testing
class MockSessionHandler(SessionAwareTaskHandler):
    """Mock implementation for testing."""
    
    def __init__(self, name="mock_session", session_store=None, token_threshold=4000, summarization_strategy="key_points"):
        with patch('a2a_server.tasks.handlers.session_aware_task_handler.InfiniteConversationManager', MockInfiniteConversationManager), \
             patch('a2a_server.tasks.handlers.session_aware_task_handler.Session', MockSession):
            super().__init__(name, session_store, token_threshold, summarization_strategy)
        
        # Create test session map for testing
        self._session_map = {
            "test_a2a_session": "test_agent_session",
            "empty_session": "empty_agent_session"
        }
        # For spying on method calls
        self._llm_call_args = []
    
    async def _llm_call(self, messages: List[Dict[str, Any]], model: str = "default") -> str:
        """Mock implementation of _llm_call."""
        self._llm_call_args.append((messages, model))
        if messages and "summarize" in str(messages):
            return "This is a summary of the conversation."
        return "This is a mock LLM response."
    
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
            agent_session_id = self._get_agent_session_id(session_id)
            if agent_session_id:
                await self.add_to_session(agent_session_id, "Test message", False)
        
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
    store.list_sessions = AsyncMock(return_value=["test_agent_session", "empty_agent_session"])
    return store


@pytest.fixture
def handler(mock_session_store):
    """Fixture for a SessionAwareTaskHandler instance."""
    with patch('a2a_server.tasks.handlers.session_aware_task_handler.Session', MockSession), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.InfiniteConversationManager', MockInfiniteConversationManager), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.SessionStoreProvider', MockSessionStoreProvider), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.EventSource', MockEventSource), \
         patch('asyncio.run') as mock_run:
        
        # Set up asyncio.run to return a mock session
        session = MagicMock()
        session.id = "new_agent_session"
        mock_run.return_value = session
        
        # Set store before handler creation
        MockSessionStoreProvider.set_store(mock_session_store)
        
        handler = MockSessionHandler("test_handler", mock_session_store)
        yield handler
        
        # Clear references to avoid warnings
        MockSessionStoreProvider._store = None


@pytest.mark.asyncio
async def test_initialization():
    """Test initialization of SessionAwareTaskHandler."""
    with patch('a2a_server.tasks.handlers.session_aware_task_handler.InfiniteConversationManager', MockInfiniteConversationManager), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.Session', MockSession):
        # Test with default params
        handler = MockSessionHandler(name="test_handler")
        assert handler.name == "test_handler"
        assert handler._session_map == {
            "test_a2a_session": "test_agent_session",
            "empty_session": "empty_agent_session"
        }
        
        # Test with custom token threshold and strategy
        handler = MockSessionHandler(
            name="custom_handler",
            token_threshold=2000,
            summarization_strategy="query_focused"
        )
        
        # Verify conversation manager has correct parameters
        assert handler._conversation_manager.token_threshold == 2000
        assert handler._conversation_manager.summarization_strategy == "query_focused"


@pytest.mark.asyncio
async def test_get_agent_session_id(handler):
    """Test _get_agent_session_id method."""
    # Test with existing session
    agent_session_id = handler._get_agent_session_id("test_a2a_session")
    assert agent_session_id == "test_agent_session"
    
    # Test with no session ID
    assert handler._get_agent_session_id(None) is None
    
    # Test with new session creation
    with patch('asyncio.run') as mock_run, \
         patch('asyncio.get_event_loop') as mock_get_loop:
        
        # Set up asyncio mocks
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = False
        mock_get_loop.return_value = mock_loop
        
        # Set up session return
        session = MagicMock()
        session.id = "new_agent_session"
        mock_run.return_value = session
        
        # Test method
        agent_session_id = handler._get_agent_session_id("new_a2a_session")
        assert agent_session_id == "new_agent_session"
        assert handler._session_map["new_a2a_session"] == "new_agent_session"
    
    # Test error handling
    with patch('asyncio.run') as mock_run:
        mock_run.side_effect = Exception("Session creation failed")
        agent_session_id = handler._get_agent_session_id("error_session")
        assert agent_session_id is None


@pytest.mark.asyncio
async def test_add_to_session(handler):
    """Test add_to_session method."""
    # Ensure conversation manager is properly mocked
    handler._conversation_manager.process_message = AsyncMock(return_value=None)
    
    # Test adding user message
    result = await handler.add_to_session("test_agent_session", "Hello", False)
    assert result is True
    
    # Verify conversation manager was called
    handler._conversation_manager.process_message.assert_called_with(
        "test_agent_session",
        "Hello",
        MockEventSource.USER,
        handler._llm_call
    )
    
    # Test adding agent message
    handler._conversation_manager.process_message.reset_mock()
    result = await handler.add_to_session("test_agent_session", "Hi there", True)
    assert result is True
    
    # Verify conversation manager was called with LLM source
    handler._conversation_manager.process_message.assert_called_with(
        "test_agent_session",
        "Hi there",
        MockEventSource.LLM,
        handler._llm_call
    )
    
    # Test error handling
    handler._conversation_manager.process_message.side_effect = Exception("Failed to add message")
    result = await handler.add_to_session("test_agent_session", "Error message", False)
    assert result is False


@pytest.mark.asyncio
async def test_get_context(handler):
    """Test get_context method."""
    # Ensure conversation manager is properly mocked
    expected_context = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "How are you?"}
    ]
    handler._conversation_manager.build_context_for_llm = AsyncMock(return_value=expected_context)
    
    # Test getting context
    context = await handler.get_context("test_agent_session")
    assert context == expected_context
    
    # Verify conversation manager was called
    handler._conversation_manager.build_context_for_llm.assert_called_with("test_agent_session")
    
    # Test error handling
    handler._conversation_manager.build_context_for_llm.side_effect = Exception("Failed to get context")
    context = await handler.get_context("test_agent_session")
    assert context is None


@pytest.mark.asyncio
async def test_llm_call():
    """Test _llm_call abstract method."""
    with patch('a2a_server.tasks.handlers.session_aware_task_handler.InfiniteConversationManager', MockInfiniteConversationManager), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.Session', MockSession):
        handler = MockSessionHandler()
        
        # Test with normal messages
        result = await handler._llm_call([{"role": "user", "content": "Hello"}], "gpt-4")
        assert result == "This is a mock LLM response."
        assert handler._llm_call_args[-1] == ([{"role": "user", "content": "Hello"}], "gpt-4")
        
        # Test with summary request
        result = await handler._llm_call([
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "Please summarize the conversation"}
        ], "gpt-3.5")
        assert result == "This is a summary of the conversation."
        assert handler._llm_call_args[-1] == ([
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "Please summarize the conversation"}
        ], "gpt-3.5")
        
        # Test with abstract class directly
        with pytest.raises(NotImplementedError):
            # Custom test class
            class TestHandler(SessionAwareTaskHandler):
                async def process_task(self, task_id, message, session_id=None):
                    pass
            
            # Need to patch these since we're instantiating the class
            with patch('a2a_server.tasks.handlers.session_aware_task_handler.InfiniteConversationManager', MockInfiniteConversationManager), \
                 patch('a2a_server.tasks.handlers.session_aware_task_handler.Session', MockSession), \
                 patch('a2a_server.tasks.handlers.session_aware_task_handler.SESSIONS_AVAILABLE', True):
                handler = TestHandler("test")
                await handler._llm_call([])


@pytest.mark.asyncio
async def test_get_conversation_history(handler):
    """Test get_conversation_history method."""
    # Setup mock history return value
    expected_history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "How are you?"}
    ]
    
    handler._conversation_manager.get_full_conversation_history = AsyncMock(return_value=[
        ("user", "USER", "Hello"),
        ("assistant", "LLM", "Hi there"),
        ("user", "USER", "How are you?")
    ])
    
    # Test with valid session
    history = await handler.get_conversation_history("test_a2a_session")
    assert history == expected_history
    
    # Verify conversation manager was called
    handler._conversation_manager.get_full_conversation_history.assert_called_with(
        "test_agent_session"
    )
    
    # Test with non-existent session
    history = await handler.get_conversation_history("nonexistent_session")
    assert history == []
    
    # Test with no session ID
    history = await handler.get_conversation_history(None)
    assert history == []
    
    # Test error handling
    handler._conversation_manager.get_full_conversation_history.side_effect = Exception("Failed to get history")
    history = await handler.get_conversation_history("test_a2a_session")
    assert history == []


@pytest.mark.asyncio
async def test_get_token_usage(handler, mock_session_store):
    """Test get_token_usage method."""
    # Mock session with token usage
    mock_token_summary = MagicMock()
    mock_token_summary.usage_by_model = {
        "gpt-4": MagicMock(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost_usd=0.003
        ),
        "gpt-3.5-turbo": MagicMock(
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            estimated_cost_usd=0.001
        )
    }
    
    mock_session = MagicMock()
    mock_session.total_tokens = 450
    mock_session.total_cost = 0.004
    mock_session.token_summary = mock_token_summary
    
    # Set up store to return our mock session
    mock_session_store.get.return_value = mock_session
    
    # Test with valid session
    usage = await handler.get_token_usage("test_a2a_session")
    assert usage["total_tokens"] == 450
    assert usage["total_cost_usd"] == 0.004
    assert len(usage["by_model"]) == 2
    assert usage["by_model"]["gpt-4"]["total_tokens"] == 150
    assert usage["by_model"]["gpt-3.5-turbo"]["cost_usd"] == 0.001
    
    # Verify store was called
    mock_session_store.get.assert_called_with("test_agent_session")
    
    # Test with non-existent session
    usage = await handler.get_token_usage("nonexistent_session")
    assert usage == {"total_tokens": 0, "total_cost": 0}
    
    # Test with no session ID
    usage = await handler.get_token_usage(None)
    assert usage == {"total_tokens": 0, "total_cost": 0}
    
    # Test with session not found in store
    mock_session_store.get.return_value = None
    usage = await handler.get_token_usage("test_a2a_session")
    assert usage == {"total_tokens": 0, "total_cost": 0}
    
    # Test error handling
    mock_session_store.get.side_effect = Exception("Failed to get session")
    usage = await handler.get_token_usage("test_a2a_session")
    assert usage == {"total_tokens": 0, "total_cost": 0}


@pytest.mark.asyncio
async def test_process_task_integration(handler):
    """Test integration with process_task."""
    # Reset the mocks
    handler._conversation_manager.process_message.reset_mock()
    handler._conversation_manager.process_message = AsyncMock()
    
    message = Message(
        role="user",
        parts=[TextPart(type="text", text="Hello, test message")]
    )
    
    # Collect events
    events = []
    async for event in handler.process_task("task123", message, "test_a2a_session"):
        events.append(event)
    
    # Check events
    assert len(events) == 2
    assert isinstance(events[0], TaskStatusUpdateEvent)
    assert events[0].status.state == TaskState.working
    assert events[0].final is False
    
    assert isinstance(events[1], TaskStatusUpdateEvent)
    assert events[1].status.state == TaskState.completed
    assert events[1].final is True
    
    # Verify session functionality was used
    handler._conversation_manager.process_message.assert_called_once()