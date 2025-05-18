# File: tests/tasks/handlers/adk/test_session_enabled_adk_handler.py
import pytest
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import List, Dict, Any, Optional, AsyncIterable

from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

# ---- Mock classes for dependencies ----

class MockEventSource:
    USER = "user"
    LLM = "llm"

class MockEventType:
    MESSAGE = "message"
    SUMMARY = "summary"

class MockSession:
    @staticmethod
    def create():
        """Non-async version that returns a pre-completed future."""
        session = MagicMock()
        session.id = "new_agent_session"
        future = asyncio.Future()
        future.set_result(session)
        return future

class MockSummarizationStrategy:
    KEY_POINTS = "key_points"
    BASIC = "basic"
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
            ("user", "user", "Hello"),
            ("assistant", "llm", "Hi there"),
            ("user", "user", "How are you?")
        ])

class MockSessionStoreProvider:
    _store = None
    
    @staticmethod
    def set_store(store):
        MockSessionStoreProvider._store = store
    
    @staticmethod
    def get_store():
        return MockSessionStoreProvider._store

# Mock Google ADK Agent implementation
class MockGoogleADKAgent:
    def __init__(self):
        self.invoke_calls = []
        self.SUPPORTED_CONTENT_TYPES = ["text/plain"]
    
    def invoke(self, query, session_id=None):
        self.invoke_calls.append((query, session_id))
        if "summarize" in query.lower():
            return "This is a summary of the conversation."
        return f"Response to: {query}"
    
    async def stream(self, query, session_id=None):
        # This won't be used in these tests, but added for completeness
        yield {"is_task_complete": True, "content": f"Stream response to: {query}"}

# Create a dictionary of mocks for patching
mock_modules = {
    'chuk_session_manager.models.event_source': MagicMock(EventSource=MockEventSource),
    'chuk_session_manager.models.event_type': MagicMock(EventType=MockEventType),
    'chuk_session_manager.models.session': MagicMock(Session=MockSession),
    'chuk_session_manager.storage': MagicMock(SessionStoreProvider=MockSessionStoreProvider),
    'chuk_session_manager.infinite_conversation': MagicMock(
        InfiniteConversationManager=MockInfiniteConversationManager,
        SummarizationStrategy=MockSummarizationStrategy
    ),
}

# Patch modules for import
with patch.dict('sys.modules', mock_modules):
    # Force SESSIONS_AVAILABLE to be True for tests
    with patch('a2a_server.tasks.handlers.session_aware_task_handler.SESSIONS_AVAILABLE', True):
        from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler
        from a2a_server.tasks.handlers.adk.google_adk_protocol import GoogleADKAgentProtocol
        # Update the import to use the correct path
        from a2a_server.tasks.handlers.adk.session_enabled_adk_handler import SessionEnabledADKHandler


# Test fixtures
@pytest.fixture
def mock_agent():
    """Fixture for a mock Google ADK agent."""
    agent = MockGoogleADKAgent()
    return agent


@pytest.fixture
def mock_session_store():
    """Fixture for a mock session store."""
    store = MagicMock()
    store.get = AsyncMock()
    store.list_sessions = AsyncMock(return_value=["test_agent_session", "empty_agent_session"])
    return store


@pytest.fixture
def handler(mock_agent, mock_session_store):
    """Fixture for a SessionEnabledADKHandler instance."""
    with patch('a2a_server.tasks.handlers.session_aware_task_handler.Session', MockSession), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.InfiniteConversationManager', MockInfiniteConversationManager), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.SessionStoreProvider', MockSessionStoreProvider), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.EventSource', MockEventSource):
        
        # Set store before handler creation
        MockSessionStoreProvider.set_store(mock_session_store)
        
        # Create the handler
        handler = SessionEnabledADKHandler(
            agent=mock_agent,
            name="test_adk_handler",
            session_store=mock_session_store
        )
        
        # Add some test session mappings
        handler._session_map = {
            "test_a2a_session": "test_agent_session",
            "empty_session": "empty_agent_session"
        }
        
        yield handler
        
        # Clear references to avoid warnings
        MockSessionStoreProvider._store = None


# Tests
@pytest.mark.asyncio
async def test_initialization(mock_agent, mock_session_store):
    """Test initialization of SessionEnabledADKHandler."""
    with patch('a2a_server.tasks.handlers.session_aware_task_handler.InfiniteConversationManager', MockInfiniteConversationManager), \
         patch('a2a_server.tasks.handlers.session_aware_task_handler.Session', MockSession):
        
        # Test with default params
        handler = SessionEnabledADKHandler(
            agent=mock_agent,
            name="test_handler",
            session_store=mock_session_store
        )
        
        assert handler.name == "test_handler"
        assert handler._agent == mock_agent
        assert isinstance(handler._conversation_manager, MockInfiniteConversationManager)
        assert handler._conversation_manager.token_threshold == 4000
        assert handler._conversation_manager.summarization_strategy == "key_points"
        
        # Test with custom params
        handler = SessionEnabledADKHandler(
            agent=mock_agent,
            name="custom_handler",
            session_store=mock_session_store,
            token_threshold=2000,
            summarization_strategy="query_focused"
        )
        
        assert handler.name == "custom_handler"
        assert handler._agent == mock_agent
        assert handler._conversation_manager.token_threshold == 2000
        assert handler._conversation_manager.summarization_strategy == "query_focused"


@pytest.mark.asyncio
async def test_llm_call_for_summary(handler, mock_agent):
    """Test _llm_call method with a summary request."""
    # Create a summary request
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "How are you?"},
        {"role": "system", "content": "Please summarize the conversation"}
    ]
    
    # Call the method
    with patch('asyncio.to_thread', new=AsyncMock(side_effect=lambda f, *args: f(*args))) as mock_to_thread:
        result = await handler._llm_call(messages, "gpt-4")
    
    # Verify the result
    assert result == "This is a summary of the conversation."
    assert mock_agent.invoke_calls[-1][0].startswith("Please summarize the following conversation:")
    assert "USER: Hello" in mock_agent.invoke_calls[-1][0]
    assert "USER: How are you?" in mock_agent.invoke_calls[-1][0]
    
    # The model parameter should be ignored
    mock_to_thread.assert_called_once()


@pytest.mark.asyncio
async def test_llm_call_regular_message(handler, mock_agent):
    """Test _llm_call method with regular message."""
    # Create a regular message list
    messages = [
        {"role": "assistant", "content": "How can I help you?"},
        {"role": "user", "content": "What's the weather today?"}
    ]
    
    # Call the method
    with patch('asyncio.to_thread', new=AsyncMock(side_effect=lambda f, *args: f(*args))):
        result = await handler._llm_call(messages, "gpt-4")
    
    # Verify the result - should use last user message
    assert result == "Response to: What's the weather today?"
    assert mock_agent.invoke_calls[-1][0] == "What's the weather today?"


@pytest.mark.asyncio
async def test_llm_call_no_user_message(handler, mock_agent):
    """Test _llm_call method with no user message."""
    # Create a message list with no user message
    messages = [
        {"role": "assistant", "content": "How can I help you?"},
        {"role": "system", "content": "Some system message"}
    ]
    
    # Call the method
    with patch('asyncio.to_thread', new=AsyncMock(side_effect=lambda f, *args: f(*args))):
        result = await handler._llm_call(messages, "gpt-4")
    
    # Verify the result - should return default message
    assert result == "I don't have enough context to respond."


@pytest.mark.asyncio
async def test_llm_call_error_handling(handler, mock_agent):
    """Test _llm_call error handling."""
    # Create a regular message
    messages = [
        {"role": "user", "content": "What's the weather today?"}
    ]
    
    # Patch the agent's invoke method to raise an exception
    mock_agent.invoke = MagicMock(side_effect=Exception("API error"))
    
    # Call the method
    with patch('asyncio.to_thread', new=AsyncMock(side_effect=lambda f, *args: f(*args))):
        result = await handler._llm_call(messages, "gpt-4")
    
    # Verify the result - should handle the error
    assert result.startswith("Error processing request:")
    assert "API error" in result


@pytest.mark.asyncio
async def test_llm_call_summary_error_handling(handler, mock_agent):
    """Test _llm_call summary error handling."""
    # Create a summary request
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "system", "content": "Please summarize the conversation"}
    ]
    
    # Patch the agent's invoke method to raise an exception
    mock_agent.invoke = MagicMock(side_effect=Exception("API error"))
    
    # Call the method
    with patch('asyncio.to_thread', new=AsyncMock(side_effect=lambda f, *args: f(*args))):
        result = await handler._llm_call(messages, "gpt-4")
    
    # Verify the result - should handle the error for summaries
    assert result == "Error generating summary."


@pytest.mark.asyncio
async def test_process_task_not_implemented(handler):
    """Test that process_task raises NotImplementedError."""
    message = Message(
        role="user",
        parts=[TextPart(type="text", text="Hello, test message")]
    )
    
    # Fix: We need to properly await the coroutine
    with pytest.raises(NotImplementedError):
        # Simply await the coroutine instead of using async for
        await handler.process_task("task123", message, "test_a2a_session")


@pytest.mark.asyncio
async def test_inheritance_from_session_aware_handler(handler):
    """Test that SessionEnabledADKHandler inherits methods from SessionAwareTaskHandler."""
    # Test inherited methods
    
    # Test get_conversation_history
    handler._conversation_manager.get_full_conversation_history = AsyncMock(return_value=[
        ("user", "user", "Hello"),
        ("assistant", "llm", "Hi there")
    ])
    
    history = await handler.get_conversation_history("test_a2a_session")
    assert history == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"}
    ]
    
    # Test add_to_session
    handler._conversation_manager.process_message = AsyncMock()
    result = await handler.add_to_session("test_agent_session", "Test message", False)
    assert result is True
    handler._conversation_manager.process_message.assert_called_once()
    
    # Test get_context
    context = await handler.get_context("test_agent_session")
    assert len(context) == 3
    assert context[0]["role"] == "user"
    
    # Test get_agent_session_id
    assert handler._get_agent_session_id("test_a2a_session") == "test_agent_session"
    assert handler._get_agent_session_id(None) is None