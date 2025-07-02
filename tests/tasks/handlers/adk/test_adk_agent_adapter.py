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
    """Test _get_or_create_session_original with an existing session."""
    # Setup mocks
    existing_session = MockSession(session_id="existing_session")
    test_case.mock_session_service.get_session.return_value = existing_session
    
    # Call the method
    session_id = test_case.adapter._get_or_create_session_original("existing_session")
    
    # Verify result
    assert session_id == "existing_session"
    
    # Verify get_session was called
    test_case.mock_session_service.get_session.assert_called_once()

def test_get_or_create_session_new(test_case):
    """Test _get_or_create_session_original with a new session."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    new_session = MockSession(session_id="new_session")
    test_case.mock_session_service.create_session.return_value = new_session
    
    # Call the method
    session_id = test_case.adapter._get_or_create_session_original("new_session")
    
    # Verify result
    assert session_id == "new_session"
    
    # Verify create_session was called
    test_case.mock_session_service.create_session.assert_called_once()

def test_get_or_create_session_none(test_case):
    """Test _get_or_create_session_original with no session ID."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    generated_session = MockSession(session_id="generated_session_id")
    test_case.mock_session_service.create_session.return_value = generated_session
    
    # Call the method
    session_id = test_case.adapter._get_or_create_session_original(None)
    
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
    
    # Check that it was called with keyword arguments (new ADK API)
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
    # Setup run method result to return synchronous result
    run_events = [
        MockEvent(
            content=MockContent(parts=[MockPart(text="Final response to Test query")]),
            is_final=True
        )
    ]
    test_case.mock_runner.run.return_value = run_events
    
    # Call the method - stream now uses invoke internally
    results = []
    async for result in test_case.adapter.stream("Test query", "test_session"):
        results.append(result)
    
    # Verify results - should only have one final result since stream uses invoke
    assert len(results) == 1
    
    # Check final result
    assert results[0]["is_task_complete"] is True
    assert results[0]["content"] == "Final response to Test query"

@pytest.mark.asyncio
async def test_stream_no_session(test_case):
    """Test stream method with no session ID."""
    # Setup mocks
    test_case.mock_session_service.get_session.return_value = None
    test_case.mock_session_service.create_session.return_value = MockSession(session_id="generated_session_id")
    
    # Setup run method result
    run_events = [
        MockEvent(
            content=MockContent(parts=[MockPart(text="Response for session generated_session_id")]),
            is_final=True
        )
    ]
    test_case.mock_runner.run.return_value = run_events
    
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
    
    # Setup run method with events with no text
    run_events = []
    test_case.mock_runner.run.return_value = run_events
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query"):
        results.append(result)
    
    # Should only yield one result when there's no content
    assert len(results) == 1
    assert results[0]["is_task_complete"] is True
    # Should get error message for empty response
    assert "I apologize, but I didn't receive a response" in results[0]["content"]

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
    
    # Setup run method result - stream now uses invoke so only returns final result
    run_events = [
        MockEvent(
            content=MockContent(parts=[MockPart(text="Final response")]),
            is_final=True
        )
    ]
    test_case.mock_runner.run.return_value = run_events
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query"):
        results.append(result)
    
    # Verify results - stream now uses invoke so only one result
    assert len(results) == 1
    
    # Check final response
    assert results[0]["is_task_complete"] is True
    assert results[0]["content"] == "Final response"

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
    
    # Make the invoke method (which stream uses) raise an exception
    def error_invoke(*args, **kwargs):
        raise Exception("ADK streaming error")
    
    # Patch the invoke method to raise an error
    original_invoke = test_case.adapter.invoke
    test_case.adapter.invoke = error_invoke
    
    # Call the method
    results = []
    async for result in test_case.adapter.stream("Test query"):
        results.append(result)
    
    # Should yield error message instead of crashing
    assert len(results) == 1
    assert results[0]["is_task_complete"] is True
    assert "I apologize, but I encountered an error" in results[0]["content"]
    assert "ADK streaming error" in results[0]["content"]