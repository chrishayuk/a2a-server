# tests/tasks/handlers/chuk/test_chuk_agent_protocol.py
"""
Tests for ChukAgent Protocol/Interface
=====================================
Tests the protocol/interface expectations for ChukAgent implementations.
"""

import pytest
import asyncio
from typing import List, Dict, Any, Optional
from unittest.mock import MagicMock, AsyncMock


class MockCompliantChukAgent:
    """A mock agent that implements the expected ChukAgent interface."""
    
    def __init__(self, name="compliant_agent"):
        self.name = name
        self.description = "A compliant test agent"
        self.provider = "test"
        self.model = "test-model"
        self.enable_tools = True
        self.enable_sessions = True
        
    def get_system_prompt(self) -> str:
        """Return system prompt."""
        return f"You are {self.name}, a helpful AI assistant."
    
    async def get_llm_client(self):
        """Get LLM client."""
        return MagicMock()
    
    async def initialize_tools(self):
        """Initialize tools."""
        pass
    
    async def get_available_tools(self) -> List[str]:
        """Get available tools."""
        return ["weather", "calculator"]
    
    async def execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute tool calls."""
        return [{"tool_call_id": "1", "content": "Tool result"}]
    
    async def generate_tools_schema(self) -> List[Dict[str, Any]]:
        """Generate tool schema."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Get weather",
                    "parameters": {"type": "object"}
                }
            }
        ]
    
    async def complete(
        self, 
        messages: List[Dict[str, Any]], 
        use_tools: bool = True,
        session_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Complete conversation."""
        user_msg = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break
        
        return {
            "content": f"Response to: {user_msg}",
            "tool_calls": [],
            "tool_results": [],
            "usage": {"total_tokens": 100}
        }
    
    async def chat(self, user_message: str, session_id: Optional[str] = None, **kwargs) -> str:
        """Simple chat interface."""
        return f"Chat response to: {user_message}"
    
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Get conversation history."""
        return []
    
    async def get_session_stats(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get session statistics."""
        return {"total_tokens": 0, "estimated_cost": 0}
    
    async def shutdown(self):
        """Shutdown agent."""
        pass


class IncompleteChukAgent:
    """A mock agent that doesn't implement all expected methods."""
    
    def __init__(self, name="incomplete_agent"):
        self.name = name
        self.description = "An incomplete test agent"
    
    def get_system_prompt(self) -> str:
        """Return system prompt."""
        return f"You are {self.name}."
    
    # Missing many required methods


class TestChukAgentProtocol:
    """Test suite for ChukAgent protocol compliance."""

    def test_compliant_agent_interface(self):
        """Test that a compliant agent has all expected attributes and methods."""
        agent = MockCompliantChukAgent()
        
        # Required attributes
        assert hasattr(agent, 'name')
        assert hasattr(agent, 'description')
        assert hasattr(agent, 'provider')
        assert hasattr(agent, 'model')
        assert hasattr(agent, 'enable_tools')
        assert hasattr(agent, 'enable_sessions')
        
        # Required methods
        assert callable(getattr(agent, 'get_system_prompt', None))
        assert callable(getattr(agent, 'get_llm_client', None))
        assert callable(getattr(agent, 'initialize_tools', None))
        assert callable(getattr(agent, 'get_available_tools', None))
        assert callable(getattr(agent, 'execute_tools', None))
        assert callable(getattr(agent, 'generate_tools_schema', None))
        assert callable(getattr(agent, 'complete', None))
        assert callable(getattr(agent, 'chat', None))
        assert callable(getattr(agent, 'get_conversation_history', None))
        assert callable(getattr(agent, 'get_session_stats', None))
        assert callable(getattr(agent, 'shutdown', None))

    def test_incomplete_agent_interface(self):
        """Test detection of incomplete agent implementations."""
        agent = IncompleteChukAgent()
        
        # Has basic attributes
        assert hasattr(agent, 'name')
        assert hasattr(agent, 'description')
        
        # Missing critical methods
        assert not callable(getattr(agent, 'complete', None))
        assert not callable(getattr(agent, 'chat', None))
        assert not callable(getattr(agent, 'initialize_tools', None))

    @pytest.mark.asyncio
    async def test_system_prompt_interface(self):
        """Test system prompt interface."""
        agent = MockCompliantChukAgent("test_agent")
        
        prompt = agent.get_system_prompt()
        assert isinstance(prompt, str)
        assert "test_agent" in prompt
        assert len(prompt) > 0

    @pytest.mark.asyncio
    async def test_tool_management_interface(self):
        """Test tool management interface."""
        agent = MockCompliantChukAgent()
        
        # Tool initialization
        await agent.initialize_tools()
        
        # Available tools
        tools = await agent.get_available_tools()
        assert isinstance(tools, list)
        assert all(isinstance(tool, str) for tool in tools)
        
        # Tool schema generation
        schemas = await agent.generate_tools_schema()
        assert isinstance(schemas, list)
        for schema in schemas:
            assert isinstance(schema, dict)
            assert "type" in schema
            assert "function" in schema
            assert "name" in schema["function"]
            assert "description" in schema["function"]

    @pytest.mark.asyncio
    async def test_tool_execution_interface(self):
        """Test tool execution interface."""
        agent = MockCompliantChukAgent()
        
        tool_calls = [
            {
                "id": "call_1",
                "function": {
                    "name": "weather",
                    "arguments": '{"location": "test"}'
                }
            }
        ]
        
        results = await agent.execute_tools(tool_calls)
        
        assert isinstance(results, list)
        assert len(results) == len(tool_calls)
        
        for result in results:
            assert isinstance(result, dict)
            # Should have either content or error
            assert "content" in result or "error" in result

    @pytest.mark.asyncio
    async def test_completion_interface(self):
        """Test completion interface."""
        agent = MockCompliantChukAgent()
        
        messages = [
            {"role": "system", "content": "You are a test agent"},
            {"role": "user", "content": "Hello"}
        ]
        
        # Test with tools
        result = await agent.complete(messages, use_tools=True)
        
        assert isinstance(result, dict)
        assert "content" in result
        assert "tool_calls" in result
        assert "tool_results" in result
        
        # Content should be string
        assert isinstance(result["content"], (str, type(None)))
        
        # Tool calls should be list
        assert isinstance(result["tool_calls"], list)
        assert isinstance(result["tool_results"], list)
        
        # Test without tools
        result2 = await agent.complete(messages, use_tools=False)
        assert isinstance(result2, dict)
        assert "content" in result2

    @pytest.mark.asyncio
    async def test_chat_interface(self):
        """Test simple chat interface."""
        agent = MockCompliantChukAgent()
        
        response = await agent.chat("Hello there")
        
        assert isinstance(response, str)
        assert len(response) > 0
        assert "Hello there" in response

    @pytest.mark.asyncio
    async def test_session_management_interface(self):
        """Test session management interface."""
        agent = MockCompliantChukAgent()
        
        # Conversation history
        history = await agent.get_conversation_history("test_session")
        assert isinstance(history, list)
        
        # Session stats
        stats = await agent.get_session_stats("test_session")
        assert isinstance(stats, dict)
        assert "total_tokens" in stats or "estimated_cost" in stats

    @pytest.mark.asyncio
    async def test_lifecycle_management(self):
        """Test agent lifecycle management."""
        agent = MockCompliantChukAgent()
        
        # Should not raise exceptions
        await agent.initialize_tools()
        await agent.shutdown()

    @pytest.mark.asyncio
    async def test_error_handling_interface(self):
        """Test that interface methods handle errors gracefully."""
        agent = MockCompliantChukAgent()
        
        # Test with invalid tool calls
        invalid_tool_calls = [{"invalid": "format"}]
        
        try:
            results = await agent.execute_tools(invalid_tool_calls)
            # Should return results, possibly with errors
            assert isinstance(results, list)
        except Exception:
            # Or raise exceptions that can be caught
            pass
        
        # Test with empty messages
        try:
            result = await agent.complete([])
            assert isinstance(result, dict)
        except Exception:
            # Should handle gracefully
            pass

    def test_attribute_types(self):
        """Test that attributes have expected types."""
        agent = MockCompliantChukAgent()
        
        assert isinstance(agent.name, str)
        assert isinstance(agent.description, str)
        assert isinstance(agent.provider, str)
        assert isinstance(agent.enable_tools, bool)
        assert isinstance(agent.enable_sessions, bool)

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test that agent can handle concurrent operations."""
        agent = MockCompliantChukAgent()
        
        # Multiple chat operations
        tasks = [
            agent.chat(f"Message {i}")
            for i in range(3)
        ]
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 3
        for i, result in enumerate(results):
            assert isinstance(result, str)
            assert f"Message {i}" in result

    @pytest.mark.asyncio
    async def test_session_isolation(self):
        """Test session isolation in agent operations."""
        agent = MockCompliantChukAgent()
        
        # Operations with different sessions should be isolated
        result1 = await agent.chat("Test message", session_id="session1")
        result2 = await agent.chat("Test message", session_id="session2")
        
        # Both should succeed
        assert isinstance(result1, str)
        assert isinstance(result2, str)
        
        # Get separate histories
        history1 = await agent.get_conversation_history("session1")
        history2 = await agent.get_conversation_history("session2")
        
        # Should be separate (though both empty in this mock)
        assert isinstance(history1, list)
        assert isinstance(history2, list)

    @pytest.mark.asyncio
    async def test_parameter_passing(self):
        """Test parameter passing through interface methods."""
        agent = MockCompliantChukAgent()
        
        # Test completion with various parameters
        messages = [{"role": "user", "content": "Test"}]
        
        result = await agent.complete(
            messages,
            use_tools=True,
            session_id="test_session",
            temperature=0.7,
            max_tokens=100
        )
        
        assert isinstance(result, dict)
        assert "content" in result

    def test_interface_consistency(self):
        """Test consistency of interface across different agent implementations."""
        agents = [
            MockCompliantChukAgent("agent1"),
            MockCompliantChukAgent("agent2")
        ]
        
        # All agents should have same interface
        for agent in agents:
            assert hasattr(agent, 'name')
            assert hasattr(agent, 'complete')
            assert hasattr(agent, 'chat')
            assert callable(agent.get_system_prompt)
            assert callable(agent.initialize_tools)


class TestChukAgentIntegrationProtocol:
    """Test integration aspects of ChukAgent protocol."""

    @pytest.mark.asyncio
    async def test_adapter_compatibility(self):
        """Test that agents work with adapter patterns."""
        agent = MockCompliantChukAgent()
        
        # Simulate adapter usage
        class MockAdapter:
            def __init__(self, agent):
                self.agent = agent
            
            async def process(self, message):
                return await self.agent.chat(message)
        
        adapter = MockAdapter(agent)
        result = await adapter.process("Test message")
        
        assert isinstance(result, str)
        assert "Test message" in result

    @pytest.mark.asyncio
    async def test_handler_compatibility(self):
        """Test that agents work with handler patterns."""
        agent = MockCompliantChukAgent()
        
        # Simulate handler usage
        class MockHandler:
            def __init__(self, agent):
                self.agent = agent
            
            async def handle_request(self, user_input):
                # Initialize tools
                await self.agent.initialize_tools()
                
                # Get response
                response = await self.agent.chat(user_input)
                
                # Cleanup
                await self.agent.shutdown()
                
                return response
        
        handler = MockHandler(agent)
        result = await handler.handle_request("Handler test")
        
        assert isinstance(result, str)
        assert "Handler test" in result

    @pytest.mark.asyncio
    async def test_factory_pattern_compatibility(self):
        """Test that agents work with factory patterns."""
        def agent_factory(name, **kwargs):
            agent = MockCompliantChukAgent(name)
            # Apply any configuration from kwargs
            for key, value in kwargs.items():
                if hasattr(agent, key):
                    setattr(agent, key, value)
            return agent
        
        # Create agent via factory
        agent = agent_factory("factory_agent", enable_tools=False)
        
        assert agent.name == "factory_agent"
        assert agent.enable_tools is False
        
        # Should still work normally
        response = await agent.chat("Factory test")
        assert isinstance(response, str)


def test_protocol_compliance_checker():
    """Test a simple protocol compliance checker."""
    def check_chuk_agent_compliance(agent):
        """Check if an object complies with ChukAgent protocol."""
        required_attributes = ['name', 'description', 'provider', 'enable_tools']
        required_methods = [
            'get_system_prompt', 'initialize_tools', 'complete', 'chat', 'shutdown'
        ]
        
        # Check attributes
        for attr in required_attributes:
            if not hasattr(agent, attr):
                return False, f"Missing attribute: {attr}"
        
        # Check methods
        for method in required_methods:
            if not callable(getattr(agent, method, None)):
                return False, f"Missing or non-callable method: {method}"
        
        return True, "Compliant"
    
    # Test compliant agent
    compliant_agent = MockCompliantChukAgent()
    is_compliant, message = check_chuk_agent_compliance(compliant_agent)
    assert is_compliant is True
    assert message == "Compliant"
    
    # Test incomplete agent
    incomplete_agent = IncompleteChukAgent()
    is_compliant, message = check_chuk_agent_compliance(incomplete_agent)
    assert is_compliant is False
    assert "Missing" in message


if __name__ == "__main__":
    # Manual test runner for development
    import asyncio
    
    async def manual_test():
        agent = MockCompliantChukAgent("manual_test_agent")
        
        print(f"Testing {agent.name} protocol compliance...")
        
        # Test basic operations
        prompt = agent.get_system_prompt()
        print(f"System prompt: {prompt[:50]}...")
        
        await agent.initialize_tools()
        print("Tools initialized")
        
        tools = await agent.get_available_tools()
        print(f"Available tools: {tools}")
        
        response = await agent.chat("Hello protocol test")
        print(f"Chat response: {response}")
        
        await agent.shutdown()
        print("Agent shutdown")
        
        print("Protocol compliance test completed!")
    
    # Uncomment to run manual test
    # asyncio.run(manual_test())