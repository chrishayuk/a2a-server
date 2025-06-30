# File: tests/tasks/handlers/adk/test_adk_agent_adapter.py
import pytest
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
from typing import List, Dict, Any, Optional, AsyncIterable, Callable

# ---- Mock classes for Google ADK dependencies ----

class MockPart:
    def __init__(self, text=""):
        self.text = text

class MockContent:
    def __init__(self, role=None, parts=None):
        self.role = role
        self.parts = parts or []

class MockSession:
    def __init__(self, session_id="test_session_1"):
        self.id = session_id

class MockEvent:
    def __init__(self, content=None, is_final=False):
        self.content = content
        self._is_final = is_final
    
    def is_final_response(self):
        return self._is_final

# Create a special TestCase base class that will handle mocking
class ADKAgentAdapterTestCase(unittest.TestCase):
    def setUp(self):
        # Create mocks
        self.mock_agent = MagicMock()
        self.mock_agent.name = "test_agent"
        self.mock_agent.SUPPORTED_CONTENT_TYPES = ["text/plain"]
        
        self.mock_session = MockSession(session_id="test_session")
        
        self.mock_session_service = MagicMock()
        self.mock_session_service.get_session = MagicMock()
        self.mock_session_service.create_session = MagicMock(return_value=self.mock_session)
        
        self.mock_runner = MagicMock()
        self.mock_runner.app_name = "test_agent"
        self.mock_runner.session_service = self.mock_session_service
        self.mock_runner.run = MagicMock()
        self.mock_runner.run_async = AsyncMock()
        
        # Store all patches
        self.patches = []
        
        # Create all patches
        mock_types = MagicMock()
        mock_types.Content = MockContent
        mock_types.Part = MagicMock()
        mock_types.Part.from_text = MagicMock(side_effect=lambda text: MockPart(text))
        
        self.patches.append(patch('a2a_server.tasks.handlers.adk.adk_agent_adapter.Runner',
                                return_value=self.mock_runner))
        self.patches.append(patch('a2a_server.tasks.handlers.adk.adk_agent_adapter.types', mock_types))
        
        # Start all patches
        for p in self.patches:
            p.start()
            
        # Import the adapter after patching
        from a2a_server.tasks.handlers.adk.adk_agent_adapter import ADKAgentAdapter
        self.ADKAgentAdapter = ADKAgentAdapter
        
        # Create the adapter
        self.adapter = ADKAgentAdapter(agent=self.mock_agent, user_id="test_user")
    
    def tearDown(self):
        # Stop all patches
        for p in self.patches:
            p.stop()

# Now define pytest functions that use our TestCase
@pytest.fixture
def test_case():
    """Return an initialized test case with all mocks set up."""
    tc = ADKAgentAdapterTestCase()
    tc.setUp()
    yield tc
    tc.tearDown()

def test_initialization(test_case):
    """Test initialization of ADKAgentAdapter."""
    # Check adapter properties
    assert test_case.adapter._agent == test_case.mock_agent
    assert test_case.adapter._user_id == "test_user"
    assert test_case.adapter.SUPPORTED_CONTENT_TYPES == ["text/plain"]
    assert test_case.adapter._runner == test_case.mock_runner

def test_get_or_create_session_existing(test_case):
    """Test _get_or_create_session with an existing session."""
    # Setup mocks
    existing_session = MockSession(session_id="existing_session")
    test_case.mock_session_service.get_session.return_value = existing_session
    
    # Call the method
    session_id = test_case.adapter._get_or_create_session("existing_session")
    
    # Verify result
    assert session_id == "existing_session"
    
    # Verify get_session was called
    test_case.mock_session_service.get_session.assert_called_once()

def test_get_or_create_session_new(test_case):
    """Test _get_or_create_session with a new session."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    new_session = MockSession(session_id="new_session")
    test_case.mock_session_service.create_session.return_value = new_session
    
    # Call the method
    session_id = test_case.adapter._get_or_create_session("new_session")
    
    # Verify result
    assert session_id == "new_session"
    
    # Verify create_session was called
    test_case.mock_session_service.create_session.assert_called_once()

def test_get_or_create_session_none(test_case):
    """Test _get_or_create_session with no session ID."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    generated_session = MockSession(session_id="generated_session_id")
    test_case.mock_session_service.create_session.return_value = generated_session
    
    # Call the method
    session_id = test_case.adapter._get_or_create_session(None)
    
    # Verify result
    assert session_id == "generated_session_id"
    
    # Verify create_session was called with None
    test_case.mock_session_service.create_session.assert_called_once()
    call_kwargs = test_case.mock_session_service.create_session.call_args.kwargs
    assert call_kwargs['session_id'] is None

def test_invoke(test_case):
    """Test invoke method."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="test_session")
    
    # Setup run method result
    run_events = [
        MockEvent(
            content=MockContent(parts=[
                MockPart(text="Hello"),
                MockPart(text=" world")
            ]),
            is_final=True
        )
    ]
    test_case.mock_runner.run.return_value = run_events
    
    # Call the method
    result = test_case.adapter.invoke("Test query", "test_session")
    
    # Verify result
    assert result == "Hello world"
    
    # Verify runner was called
    test_case.mock_runner.run.assert_called_once()
    
    # FIXED: Check that it was called with keyword arguments (new ADK API)
    call_kwargs = test_case.mock_runner.run.call_args.kwargs
    assert call_kwargs["user_id"] == "test_user"
    assert call_kwargs["session_id"] == "test_session"
    assert "new_message" in call_kwargs

def test_invoke_empty_response(test_case):
    """Test invoke method with empty response."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="test_session")
    
    # Test case: No events
    test_case.mock_runner.run.return_value = []
    result = test_case.adapter.invoke("Test query")
    assert "I apologize, but I didn't receive a response" in result
    
    # Test case: Event with no content
    test_case.mock_runner.run.return_value = [MockEvent()]
    result = test_case.adapter.invoke("Test query")
    assert "I apologize, but I couldn't generate a response" in result
    
    # Test case: Event with content but no parts
    test_case.mock_runner.run.return_value = [MockEvent(content=MockContent(parts=[]))]
    result = test_case.adapter.invoke("Test query")
    # The adapter returns the generic "couldn't generate a response" message for this case
    assert "I apologize, but I couldn't generate a response" in result

@pytest.mark.asyncio
async def test_stream(test_case):
    """Test stream method."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="test_session")
    
    # Setup run_async method result
    async def mock_run_async(**kwargs):  # FIXED: Use **kwargs to match new API
        yield MockEvent(
            content=MockContent(parts=[MockPart(text="Thinking about Test query")]),
            is_final=False
        )
        yield MockEvent(
            content=MockContent(parts=[MockPart(text="Final response to Test query")]),
            is_final=True
        )
    
    test_case.mock_runner.run_async = mock_run_async
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query", "test_session"):
        results.append(result)
    
    # Verify results
    assert len(results) == 2
    
    # Check first (intermediate) result
    assert results[0]["is_task_complete"] is False
    assert results[0]["updates"] == "Thinking about Test query"
    
    # Check final result
    assert results[1]["is_task_complete"] is True
    assert results[1]["content"] == "Final response to Test query"

@pytest.mark.asyncio
async def test_stream_no_session(test_case):
    """Test stream method with no session ID."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="generated_session_id")
    
    # Setup run_async method result
    async def mock_run_async(**kwargs):  # FIXED: Use **kwargs
        # Capture the session ID from kwargs
        session_id = kwargs.get("session_id")
        
        # Yield a result with the session ID
        yield MockEvent(
            content=MockContent(parts=[MockPart(text=f"Response for session {session_id}")]),
            is_final=True
        )
    
    test_case.mock_runner.run_async = mock_run_async
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query"):
        results.append(result)
    
    # Verify results - should be one result with the generated session ID
    assert len(results) == 1
    assert results[0]["content"] == "Response for session generated_session_id"

@pytest.mark.asyncio
async def test_stream_with_empty_parts(test_case):
    """Test stream method with events that have empty parts."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="test_session")
    
    # Setup run_async method with events with no text
    async def mock_run_async(**kwargs):  # FIXED: Use **kwargs
        # Event with no content
        yield MockEvent(is_final=False)
        
        # Event with content but empty parts
        yield MockEvent(content=MockContent(parts=[]), is_final=False)
        
        # Event with parts that have no text attribute
        no_text_part = MagicMock()
        del no_text_part.text  # Remove text attribute
        yield MockEvent(
            content=MockContent(parts=[no_text_part]),
            is_final=True
        )
    
    test_case.mock_runner.run_async = mock_run_async
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query"):
        results.append(result)
    
    # FIXED: Should only yield results when there's actual content or when final
    # The intermediate events with no content don't yield results in the current implementation
    assert len(results) == 1  # Only the final result
    assert results[0]["is_task_complete"] is True
    # FIXED: Should get error message for empty final response
    assert "I apologize, but my response was empty" in results[0]["content"]

def test_text_extraction(test_case):
    """Test text extraction from parts."""
    # Test with valid parts
    parts = [MockPart(text="Hello "), MockPart(text="world!")]
    result = test_case.adapter._extract_text_from_parts(parts)
    assert result == "Hello world!"
    
    # Test with empty parts
    parts = [MockPart(text=""), MockPart(text=None)]
    result = test_case.adapter._extract_text_from_parts(parts)
    assert result == ""
    
    # Test with mixed parts (None text should be skipped)
    parts = [MockPart(text="Valid"), MockPart(text=""), MockPart(text="text")]
    result = test_case.adapter._extract_text_from_parts(parts)
    assert result == "Validtext"

def test_response_validation(test_case):
    """Test response validation."""
    # Test valid response
    result = test_case.adapter._validate_response("This is a valid response.")
    assert result == "This is a valid response."
    
    # Test empty response
    result = test_case.adapter._validate_response("")
    assert "I apologize, but my response was empty" in result
    
    # Test malformed response
    result = test_case.adapter._validate_response("I'm You are confused")
    assert "I apologize, but I encountered an issue" in result

@pytest.mark.asyncio
async def test_stream_with_intermediate_updates(test_case):
    """Test stream method with intermediate updates."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = MockSession(session_id="test_session")
    
    # Setup run_async method with intermediate updates
    async def mock_run_async(**kwargs):
        # Intermediate update - using "Processing..." which gets cleaned to "Processing."
        yield MockEvent(
            content=MockContent(parts=[MockPart(text="Processing...")]),
            is_final=False
        )
        
        # Another intermediate update  
        yield MockEvent(
            content=MockContent(parts=[MockPart(text="Still working...")]),
            is_final=False
        )
        
        # Final response
        yield MockEvent(
            content=MockContent(parts=[MockPart(text="Final response")]),
            is_final=True
        )
    
    test_case.mock_runner.run_async = mock_run_async
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query"):
        results.append(result)
    
    # Verify results
    assert len(results) == 3
    
    # Check intermediate updates - the adapter cleans "..." to "."
    assert results[0]["is_task_complete"] is False
    assert results[0]["updates"] == "Processing."  # Adapter cleans duplicate periods
    
    assert results[1]["is_task_complete"] is False
    assert results[1]["updates"] == "Still working."  # Adapter cleans duplicate periods
    
    # Check final response
    assert results[2]["is_task_complete"] is True
    assert results[2]["content"] == "Final response"

def test_error_handling_in_invoke(test_case):
    """Test error handling in invoke method."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="test_session")
    
    # Make runner.run raise an exception
    test_case.mock_runner.run.side_effect = Exception("ADK runner error")
    
    # Call the method
    result = test_case.adapter.invoke("Test query")
    
    # Should return error message instead of crashing
    assert "I apologize, but I encountered an error" in result
    assert "ADK runner error" in result

@pytest.mark.asyncio
async def test_error_handling_in_stream(test_case):
    """Test error handling in stream method."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="test_session")
    
    # Create a proper async generator that raises an exception when iterated
    class AsyncIteratorThatRaises:
        def __aiter__(self):
            return self
        
        async def __anext__(self):
            raise Exception("ADK streaming error")
    
    # Mock run_async to return our async iterator that raises an exception
    test_case.mock_runner.run_async = lambda **kwargs: AsyncIteratorThatRaises()
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query"):
        results.append(result)
    
    # Should yield error message instead of crashing
    assert len(results) == 1
    assert results[0]["is_task_complete"] is True
    assert "I apologize, but I encountered an error" in results[0]["content"]
    assert "ADK streaming error" in results[0]["content"]