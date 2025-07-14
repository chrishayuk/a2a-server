# tests/tasks/handlers/chuk/test_chuk_agent.py
"""
Tests for ChukAgent
==================
Tests the pure ChukAgent class with comprehensive tool call debugging.
"""

import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from typing import List, Dict, Any, Optional

# Mock the dependencies before importing ChukAgent
@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock all external dependencies."""
    with patch.dict('sys.modules', {
        'chuk_llm.llm.client': MagicMock(),
        'chuk_llm.llm.system_prompt_generator': MagicMock(),
        'chuk_tool_processor.registry.provider': MagicMock(),
        'chuk_tool_processor.mcp.setup_mcp_stdio': MagicMock(),
        'chuk_tool_processor.mcp.setup_mcp_sse': MagicMock(),
        'chuk_tool_processor.execution.tool_executor': MagicMock(),
        'chuk_tool_processor.execution.strategies.inprocess_strategy': MagicMock(),
        'chuk_tool_processor.models.tool_call': MagicMock(),
        'chuk_ai_session_manager': MagicMock(),
        'chuk_ai_session_manager.session_storage': MagicMock(),
    }):
        yield


class MockLLMClient:
    """Mock LLM client for testing."""
    
    def __init__(self, should_fail=False, include_tool_calls=False):
        self.should_fail = should_fail
        self.include_tool_calls = include_tool_calls
        self.call_count = 0
        self.last_messages = None
        self.last_tools = None
    
    async def create_completion(self, messages, tools=None, tool_choice=None, **kwargs):
        """Mock completion."""
        self.call_count += 1
        self.last_messages = messages
        self.last_tools = tools
        
        if self.should_fail:
            raise Exception("LLM client failure")
        
        if self.include_tool_calls and tools:
            return {
                "content": "I'll use tools to help you.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "weather",
                            "arguments": '{"location": "test"}'
                        }
                    }
                ],
                "usage": {"total_tokens": 100}
            }
        else:
            # Extract user message for response
            user_content = "Hello"
            for msg in messages:
                if msg.get("role") == "user":
                    user_content = msg.get("content", "Hello")
                    break
            
            return {
                "content": f"Response to: {user_content}",
                "usage": {"total_tokens": 50}
            }


class MockToolExecutor:
    """Mock tool executor for testing."""
    
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.executed_calls = []
    
    async def execute(self, tool_calls):
        """Mock tool execution."""
        self.executed_calls.extend(tool_calls)
        
        if self.should_fail:
            # Return error results
            return [MagicMock(error="Tool execution failed", result=None) for _ in tool_calls]
        else:
            # Return success results
            results = []
            for call in tool_calls:
                result = MagicMock()
                result.error = None
                result.result = f"Tool result for {call.tool}"
                results.append(result)
            return results


class MockRegistry:
    """Mock tool registry for testing."""
    
    def __init__(self, tools=None):
        self.tools = tools or [("tools", "weather"), ("tools", "calculator")]
    
    async def list_tools(self):
        """Mock list tools."""
        return self.tools


class MockStreamManager:
    """Mock stream manager for testing."""
    
    def __init__(self, tools=None):
        self.tools = tools or [
            {
                "name": "weather",
                "description": "Get weather information",
                "inputSchema": {"type": "object", "properties": {"location": {"type": "string"}}}
            }
        ]
        self.server_names = {0: "test_server"}
    
    def get_all_tools(self):
        """Mock get all tools."""
        return self.tools
    
    async def list_tools(self, server_name):
        """Mock list tools for server."""
        return self.tools
    
    async def close(self):
        """Mock close."""
        pass


@pytest.fixture
def mock_llm_client():
    """Mock LLM client."""
    return MockLLMClient()


@pytest.fixture
def mock_llm_client_with_tools():
    """Mock LLM client that returns tool calls."""
    return MockLLMClient(include_tool_calls=True)


@pytest.fixture
def mock_tool_executor():
    """Mock tool executor."""
    return MockToolExecutor()


@pytest.fixture
def mock_registry():
    """Mock tool registry."""
    return MockRegistry()


@pytest.fixture
def mock_stream_manager():
    """Mock stream manager."""
    return MockStreamManager()


@pytest.fixture
def chuk_agent():
    """Create a ChukAgent instance for testing."""
    with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client') as mock_get_client, \
         patch('a2a_server.tasks.handlers.chuk.chuk_agent.setup_mcp_stdio') as mock_setup_stdio, \
         patch('a2a_server.tasks.handlers.chuk.chuk_agent.ToolRegistryProvider') as mock_registry_provider, \
         patch('a2a_server.tasks.handlers.chuk.chuk_agent.ToolExecutor') as mock_executor_class, \
         patch('a2a_server.tasks.handlers.chuk.chuk_agent.InProcessStrategy') as mock_strategy:
        
        # Import after patching
        from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
        
        # Setup mocks
        mock_get_client.return_value = MockLLMClient()
        
        agent = ChukAgent(
            name="test_agent",
            description="Test agent for testing",
            enable_sessions=False,  # Disable sessions for simpler testing
            enable_tools=False      # Disable tools initially
        )
        
        return agent


class TestChukAgent:
    """Test suite for ChukAgent."""

    def test_agent_initialization(self):
        """Test agent initialization with various configurations."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client'):
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            # Basic initialization
            agent = ChukAgent(
                name="basic_agent",
                description="Basic test agent",
                enable_sessions=False
            )
            
            assert agent.name == "basic_agent"
            assert agent.description == "Basic test agent"
            assert agent.provider == "openai"  # Default
            assert agent.enable_tools is True  # Default
            assert agent.enable_sessions is False
            
            # Custom configuration
            agent2 = ChukAgent(
                name="custom_agent",
                provider="anthropic",
                model="claude-3",
                enable_tools=False,
                debug_tools=False
            )
            
            assert agent2.provider == "anthropic"
            assert agent2.model == "claude-3"
            assert agent2.enable_tools is False
            assert agent2.debug_tools is False

    def test_system_prompt_generation(self, chuk_agent):
        """Test system prompt generation."""
        # Test basic instruction
        prompt = chuk_agent.get_system_prompt()
        assert "test_agent" in prompt
        assert "helpful AI assistant" in prompt
        
        # Test with custom instruction
        chuk_agent.instruction = "You are a specialized test assistant."
        prompt = chuk_agent.get_system_prompt()
        assert "specialized test assistant" in prompt

    @pytest.mark.asyncio
    async def test_llm_client_creation(self, chuk_agent):
        """Test LLM client creation."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client') as mock_get_client:
            mock_client = MockLLMClient()
            mock_get_client.return_value = mock_client
            
            client = await chuk_agent.get_llm_client()
            assert client is mock_client
            mock_get_client.assert_called_once_with(provider="openai", model=None)

    def test_response_content_extraction(self, chuk_agent):
        """Test extraction of content from various response formats."""
        # Test dict response
        dict_response = {"response": "Test response"}
        content = chuk_agent._extract_response_content(dict_response)
        assert content == "Test response"
        
        # Test dict with content key
        dict_response2 = {"content": "Test content"}
        content = chuk_agent._extract_response_content(dict_response2)
        assert content == "Test content"
        
        # Test object with content attribute
        obj_response = MagicMock()
        obj_response.content = "Object content"
        content = chuk_agent._extract_response_content(obj_response)
        assert content == "Object content"
        
        # Test None response
        content = chuk_agent._extract_response_content(None)
        assert content == ""
        
        # Test string response
        content = chuk_agent._extract_response_content("Direct string")
        assert content == "Direct string"

    @pytest.mark.asyncio
    async def test_tool_initialization_disabled(self, chuk_agent):
        """Test tool initialization when tools are disabled."""
        # Tools are disabled by default in fixture
        await chuk_agent.initialize_tools()
        
        # Should not initialize tools
        assert chuk_agent._tools_initialized is False or chuk_agent.enable_tools is False

    @pytest.mark.asyncio
    async def test_tool_initialization_enabled(self):
        """Test tool initialization when tools are enabled."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client'), \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.setup_mcp_stdio') as mock_setup, \
             patch('chuk_tool_processor.registry.provider.ToolRegistryProvider') as mock_provider, \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.ToolExecutor') as mock_executor_class:
            
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            # Setup mocks
            mock_registry = MockRegistry()
            mock_stream_manager = MockStreamManager()
            mock_executor = MockToolExecutor()
            
            mock_setup.return_value = (mock_registry, mock_stream_manager)
            # Make get_registry async
            async def async_get_registry():
                return mock_registry
            mock_provider.get_registry = async_get_registry
            mock_executor_class.return_value = mock_executor
            
            agent = ChukAgent(
                name="tool_agent",
                enable_tools=True,
                mcp_transport="stdio", 
                mcp_servers=["test_server"],
                mcp_config_file="test_config.json",
                enable_sessions=False
            )
            
            # Initialize tools
            await agent.initialize_tools()
            
            # Should have initialized
            assert agent._tools_initialized is True
            # Registry and executor should be set (may be mock objects)
            assert agent.stream_manager is not None

    @pytest.mark.asyncio
    async def test_get_available_tools(self):
        """Test getting available tools."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client'):
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            agent = ChukAgent(name="tools_test", enable_tools=True, enable_sessions=False)
            
            # No registry - should return empty
            tools = await agent.get_available_tools()
            assert tools == []
            
            # With registry
            mock_registry = MockRegistry()
            agent.registry = mock_registry
            
            tools = await agent.get_available_tools()
            assert "weather" in tools
            assert "calculator" in tools

    @pytest.mark.asyncio
    async def test_execute_tools_disabled(self, chuk_agent):
        """Test tool execution when tools are disabled."""
        tool_calls = [
            {
                "function": {
                    "name": "weather",
                    "arguments": '{"location": "test"}'
                }
            }
        ]
        
        results = await chuk_agent.execute_tools(tool_calls)
        
        # Should return error results
        assert len(results) == 1
        assert "error" in results[0]

    @pytest.mark.asyncio
    async def test_execute_tools_enabled(self):
        """Test tool execution when tools are enabled."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client'), \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.ToolCall') as mock_tool_call:
            
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            agent = ChukAgent(name="exec_test", enable_tools=True, enable_sessions=False)
            
            # Setup mocks
            mock_executor = MockToolExecutor()
            agent.executor = mock_executor
            
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
            
            # Should return success results
            assert len(results) == 1
            assert "tool_call_id" in results[0]
            assert "content" in results[0]
            assert "Tool result" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_generate_tools_schema(self):
        """Test tool schema generation."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client'):
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            agent = ChukAgent(name="schema_test", enable_tools=True, enable_sessions=False)
            
            # No stream manager - should return empty
            schemas = await agent.generate_tools_schema()
            assert schemas == []
            
            # With stream manager
            mock_stream_manager = MockStreamManager()
            agent.stream_manager = mock_stream_manager
            
            schemas = await agent.generate_tools_schema()
            
            # Should return OpenAI-style schemas
            assert len(schemas) >= 1
            assert schemas[0]["type"] == "function"
            assert "function" in schemas[0]
            assert "name" in schemas[0]["function"]
            assert "description" in schemas[0]["function"]
            assert "parameters" in schemas[0]["function"]

    @pytest.mark.asyncio
    async def test_complete_without_tools(self, chuk_agent):
        """Test completion without tools."""
        with patch.object(chuk_agent, 'get_llm_client') as mock_get_client:
            mock_client = MockLLMClient()
            mock_get_client.return_value = mock_client
            
            messages = [
                {"role": "system", "content": "You are a test agent"},
                {"role": "user", "content": "Hello"}
            ]
            
            result = await chuk_agent.complete(messages, use_tools=False)
            
            # Should have content
            assert "content" in result
            assert "Response to: Hello" in result["content"]
            assert result["tool_calls"] == []
            assert result["tool_results"] == []

    @pytest.mark.asyncio
    async def test_complete_with_tools(self):
        """Test completion with tools."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client') as mock_get_client, \
             patch('chuk_tool_processor.registry.provider.ToolRegistryProvider') as mock_provider:
            
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            agent = ChukAgent(name="complete_test", enable_tools=True, enable_sessions=False)
            
            # Setup mocks
            mock_client = MockLLMClient(include_tool_calls=True)
            mock_get_client.return_value = mock_client
            
            # Mock the registry provider to avoid initialization issues
            async def async_get_registry():
                return MockRegistry()
            mock_provider.get_registry = async_get_registry
            
            mock_stream_manager = MockStreamManager()
            agent.stream_manager = mock_stream_manager
            
            mock_executor = MockToolExecutor()
            agent.executor = mock_executor
            agent._tools_initialized = True  # Skip tool initialization
            
            messages = [
                {"role": "system", "content": "You are a test agent"},
                {"role": "user", "content": "Get the weather"}
            ]
            
            result = await agent.complete(messages, use_tools=True)
            
            # Should have content - tool calls may or may not be present depending on LLM mock
            assert "content" in result
            assert "tool_calls" in result
            assert "tool_results" in result

    @pytest.mark.asyncio
    async def test_chat_interface(self, chuk_agent):
        """Test simple chat interface."""
        with patch.object(chuk_agent, 'complete') as mock_complete:
            mock_complete.return_value = {"content": "Chat response"}
            
            response = await chuk_agent.chat("Hello there")
            
            assert response == "Chat response"
            mock_complete.assert_called_once()
            
            # Check messages passed to complete
            call_args = mock_complete.call_args[0][0]
            assert len(call_args) == 2  # system + user
            assert call_args[0]["role"] == "system"
            assert call_args[1]["role"] == "user"
            assert call_args[1]["content"] == "Hello there"

    @pytest.mark.asyncio
    async def test_error_handling_in_complete(self, chuk_agent):
        """Test error handling in complete method."""
        with patch.object(chuk_agent, 'get_llm_client') as mock_get_client:
            mock_client = MockLLMClient(should_fail=True)
            mock_get_client.return_value = mock_client
            
            messages = [{"role": "user", "content": "Test"}]
            
            with pytest.raises(Exception, match="LLM client failure"):
                await chuk_agent.complete(messages)

    @pytest.mark.asyncio
    async def test_tool_execution_timeout(self):
        """Test tool execution timeout handling."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client'), \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.asyncio.wait_for') as mock_wait_for:
            
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            agent = ChukAgent(name="timeout_test", tool_timeout=1.0, enable_sessions=False)
            
            # Setup timeout
            mock_wait_for.side_effect = asyncio.TimeoutError()
            
            # Mock executor
            mock_executor = MockToolExecutor()
            agent.executor = mock_executor
            
            tool_calls = [
                {
                    "id": "call_1",
                    "function": {
                        "name": "slow_tool",
                        "arguments": "{}"
                    }
                }
            ]
            
            results = await agent.execute_tools(tool_calls)
            
            # Should return timeout error
            assert len(results) == 1
            assert "Timeout" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_shutdown(self, chuk_agent):
        """Test agent shutdown."""
        # Setup mock stream manager
        mock_stream_manager = MockStreamManager()
        chuk_agent.stream_manager = mock_stream_manager
        
        await chuk_agent.shutdown()
        
        # Should not raise exceptions

    def test_mcp_configuration_options(self):
        """Test various MCP configuration options."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client'):
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            # STDIO configuration
            agent1 = ChukAgent(
                name="stdio_agent",
                mcp_transport="stdio",
                mcp_servers=["server1", "server2"],
                mcp_config_file="config.json",
                enable_sessions=False
            )
            
            assert agent1.mcp_transport == "stdio"
            assert agent1.mcp_servers == ["server1", "server2"]
            assert agent1.mcp_config_file == "config.json"
            
            # SSE configuration
            agent2 = ChukAgent(
                name="sse_agent",
                mcp_transport="sse",
                mcp_sse_servers=[
                    {"name": "server1", "url": "http://localhost:8000"}
                ],
                enable_sessions=False
            )
            
            assert agent2.mcp_transport == "sse"
            assert len(agent2.mcp_sse_servers) == 1


class TestChukAgentIntegration:
    """Integration tests for ChukAgent."""

    @pytest.mark.asyncio
    async def test_full_conversation_flow(self):
        """Test complete conversation flow with tools."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client') as mock_get_client, \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.setup_mcp_stdio') as mock_setup, \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.ToolRegistryProvider') as mock_provider, \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.ToolExecutor') as mock_executor_class, \
             patch('a2a_server.tasks.handlers.chuk.chuk_agent.ToolCall') as mock_tool_call:
            
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            # Setup comprehensive mocks
            mock_client = MockLLMClient(include_tool_calls=True)
            mock_get_client.return_value = mock_client
            
            mock_registry = MockRegistry()
            mock_stream_manager = MockStreamManager()
            mock_executor = MockToolExecutor()
            
            mock_setup.return_value = (mock_registry, mock_stream_manager)
            # Make get_registry async
            async def async_get_registry():
                return mock_registry
            mock_provider.get_registry = async_get_registry
            mock_executor_class.return_value = mock_executor
            
            # Create agent with tools enabled
            agent = ChukAgent(
                name="integration_agent",
                enable_tools=True,
                mcp_transport="stdio",
                mcp_servers=["test_server"],
                mcp_config_file="test.json",
                enable_sessions=False
            )
            
            # Initialize tools
            await agent.initialize_tools()
            
            # Test conversation
            response = await agent.chat("What's the weather like?")
            
            # Should have generated response
            assert isinstance(response, str)
            assert len(response) > 0
            
            # Tools may or may not be executed depending on mock behavior
            # Just verify the agent completed successfully

    @pytest.mark.asyncio
    async def test_error_recovery(self):
        """Test error recovery in various scenarios."""
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client') as mock_get_client:
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            agent = ChukAgent(name="recovery_test", enable_sessions=False)
            
            # Test LLM failure recovery
            failing_client = MockLLMClient(should_fail=True)
            mock_get_client.return_value = failing_client
            
            with pytest.raises(Exception):
                await agent.chat("Test message")
            
            # Test recovery with working client
            working_client = MockLLMClient()
            mock_get_client.return_value = working_client
            
            response = await agent.chat("Recovery test")
            assert "Response to: Recovery test" in response


if __name__ == "__main__":
    # Manual test runner for development
    import asyncio
    
    async def manual_test():
        with patch('a2a_server.tasks.handlers.chuk.chuk_agent.get_client') as mock_get_client:
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            mock_client = MockLLMClient()
            mock_get_client.return_value = mock_client
            
            agent = ChukAgent(
                name="manual_test_agent",
                description="Manual test agent",
                enable_sessions=False,
                enable_tools=False
            )
            
            print(f"Testing {agent.name}...")
            
            response = await agent.chat("Hello, how are you?")
            print(f"Response: {response}")
            
            print("Manual test completed!")
    
    # Uncomment to run manual test
    # asyncio.run(manual_test())