# File: tests/tasks/handlers/adk/test_google_adk_protocol.py
import pytest
import asyncio
from typing import List, Dict, Any, AsyncIterable, Optional

from a2a_server.tasks.handlers.adk.google_adk_protocol import GoogleADKAgentProtocol

# Test implementations of the protocol
class MockADKAgent:
    """A mock agent that implements the protocol."""
    
    SUPPORTED_CONTENT_TYPES = ["text/plain"]
    
    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        """Synchronous invocation."""
        return f"Response to: {query}" + (f" (session: {session_id})" if session_id else "")
    
    async def stream(self, query: str, session_id: Optional[str] = None) -> AsyncIterable[Dict[str, Any]]:
        """Streaming response."""
        yield {"is_task_complete": False, "content": "Thinking..."}
        await asyncio.sleep(0.01)
        content = f"Streamed response to: {query}" + (f" (session: {session_id})" if session_id else "")
        yield {"is_task_complete": True, "content": content}


class IncompleteMockAgent:
    """A mock agent that doesn't implement all protocol methods."""
    
    SUPPORTED_CONTENT_TYPES = ["text/plain"]
    
    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        """Synchronous invocation."""
        return f"Response to: {query}"
    
    # Missing stream method


class IncorrectReturnTypeAgent:
    """A mock agent with incorrect return types."""
    
    SUPPORTED_CONTENT_TYPES = ["text/plain"]
    
    def invoke(self, query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Incorrect return type (dict instead of str)."""
        return {"response": f"Response to: {query}"}
    
    async def stream(self, query: str, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Incorrect return type (List instead of AsyncIterable)."""
        return [
            {"is_task_complete": False, "content": "Thinking..."},
            {"is_task_complete": True, "content": f"Streamed response to: {query}"}
        ]


# Tests
def test_protocol_compatible_agent():
    """Test a fully compatible agent with the protocol."""
    agent = MockADKAgent()
    
    # Verify it has the required attributes
    assert hasattr(agent, "SUPPORTED_CONTENT_TYPES")
    assert isinstance(agent.SUPPORTED_CONTENT_TYPES, list)
    
    # Verify methods exist with correct signatures
    assert callable(getattr(agent, "invoke", None))
    assert callable(getattr(agent, "stream", None))
    
    # Test invoke method
    result = agent.invoke("Hello", "session123")
    assert isinstance(result, str)
    assert "Hello" in result
    assert "session123" in result
    
    # Test stream method
    stream_gen = agent.stream("Hello stream", "session456")
    assert hasattr(stream_gen, "__aiter__")
    

@pytest.mark.asyncio
async def test_protocol_streaming():
    """Test the streaming interface of the protocol."""
    agent = MockADKAgent()
    
    # Test streaming functionality
    results = []
    async for item in agent.stream("Test query", "test_session"):
        results.append(item)
    
    # Check the results
    assert len(results) == 2
    assert results[0]["is_task_complete"] is False
    assert results[1]["is_task_complete"] is True
    assert "Test query" in results[1]["content"]
    assert "test_session" in results[1]["content"]


def test_incomplete_agent():
    """Test an agent that doesn't implement all protocol methods."""
    agent = IncompleteMockAgent()
    
    # Verify it has some required attributes
    assert hasattr(agent, "SUPPORTED_CONTENT_TYPES")
    assert isinstance(agent.SUPPORTED_CONTENT_TYPES, list)
    
    # Verify invoke method exists
    assert callable(getattr(agent, "invoke", None))
    
    # Verify stream method is missing
    assert not callable(getattr(agent, "stream", None))


def test_runtime_type_checking():
    """
    Test runtime type checking of protocol implementations.
    
    Note: This test verifies that Python's runtime behavior allows
    incompatible types, since Protocol is just for static type checking.
    """
    agent = IncorrectReturnTypeAgent()
    
    # Python's runtime doesn't enforce return types
    result = agent.invoke("test")
    assert isinstance(result, dict)
    assert "Response to: test" in result["response"]


@pytest.mark.asyncio
async def test_protocol_structural_subtyping():
    """
    Test structural subtyping with Protocol.
    
    This test validates that a class can be treated as implementing
    the protocol if it provides the expected methods, even if it
    doesn't explicitly subclass or declare itself as implementing it.
    """
    # Create a class at runtime
    class DynamicAgent:
        SUPPORTED_CONTENT_TYPES = ["text/plain", "application/json"]
        
        def invoke(self, query, session_id=None):
            return f"Dynamic response to: {query}"
        
        async def stream(self, query, session_id=None):
            yield {"is_task_complete": True, "content": f"Dynamic streamed response to: {query}"}
    
    # Create an instance
    agent = DynamicAgent()
    
    # Verify it structurally matches the protocol
    assert hasattr(agent, "SUPPORTED_CONTENT_TYPES")
    assert callable(getattr(agent, "invoke", None))
    assert callable(getattr(agent, "stream", None))
    
    # Test invoke
    result = agent.invoke("Runtime test")
    assert "Runtime test" in result
    
    # Test stream
    results = []
    async for item in agent.stream("Stream test"):
        results.append(item)
    
    assert len(results) == 1
    assert results[0]["is_task_complete"] is True
    assert "Stream test" in results[0]["content"]


def test_protocol_type_checking():
    """
    Test basic runtime type compatibility.
    
    This is a simple example to show how we'd check compatibility
    at runtime if needed (though normally this would be done by
    the static type checker like mypy).
    """
    def check_protocol_compatible(obj):
        # Check attributes
        if not hasattr(obj, "SUPPORTED_CONTENT_TYPES"):
            return False
        if not isinstance(obj.SUPPORTED_CONTENT_TYPES, list):
            return False
            
        # Check methods
        if not callable(getattr(obj, "invoke", None)):
            return False
        if not callable(getattr(obj, "stream", None)):
            return False
            
        return True
    
    # Test with compatible and incompatible agents
    assert check_protocol_compatible(MockADKAgent())
    assert not check_protocol_compatible(IncompleteMockAgent())
    assert check_protocol_compatible(IncorrectReturnTypeAgent())  # Methods exist but wrong return types