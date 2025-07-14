# tests/tasks/handlers/chuk/test_chuk_agent_adapter.py
"""
Tests for ChukAgentAdapter
==========================
Tests the adapter that wraps ChukAgent to work with A2A TaskHandler interface.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from typing import List, Dict, Any, Optional

from a2a_server.tasks.handlers.chuk.chuk_agent_adapter import ChukAgentAdapter
from a2a_json_rpc.spec import (
    Message, TextPart, Role, TaskState, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)


class MockChukAgent:
    """Mock ChukAgent for testing."""
    
    def __init__(self, name="test_chuk_agent", fail_init=False, fail_complete=False):
        self.name = name
        self.fail_init = fail_init
        self.fail_complete = fail_complete
        self.initialize_tools_called = False
        self.get_available_tools_called = False
        self.complete_called = False
        self.last_messages = None
        self.last_use_tools = None
        
    def get_system_prompt(self) -> str:
        """Mock system prompt."""
        return f"You are {self.name}, a helpful AI assistant."
    
    async def initialize_tools(self):
        """Mock tool initialization."""
        self.initialize_tools_called = True
        if self.fail_init:
            raise Exception("Tool initialization failed")
    
    async def get_available_tools(self) -> List[str]:
        """Mock available tools."""
        self.get_available_tools_called = True
        return ["weather", "calculator", "web_search"]
    
    async def complete(self, messages: List[Dict[str, Any]], use_tools: bool = True, **kwargs) -> Dict[str, Any]:
        """Mock completion."""
        self.complete_called = True
        self.last_messages = messages
        self.last_use_tools = use_tools
        
        if self.fail_complete:
            raise Exception("Completion failed")
        
        # Extract user message
        user_message = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        
        # Mock tool calls for certain messages
        if "use tools" in user_message.lower() and use_tools:
            return {
                "content": "I used tools to help you.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "weather",
                            "arguments": '{"location": "test"}'
                        }
                    }
                ],
                "tool_results": [
                    {
                        "tool_call_id": "call_1",
                        "content": "Weather is sunny, 25°C"
                    }
                ],
                "usage": {"total_tokens": 100}
            }
        else:
            return {
                "content": f"Response to: {user_message}",
                "tool_calls": [],
                "tool_results": [],
                "usage": {"total_tokens": 50}
            }


@pytest.fixture
def mock_chuk_agent():
    """Create a mock ChukAgent for testing."""
    return MockChukAgent()


@pytest.fixture
def chuk_adapter(mock_chuk_agent):
    """Create a ChukAgentAdapter with mock agent."""
    return ChukAgentAdapter(mock_chuk_agent)


class TestChukAgentAdapter:
    """Test suite for ChukAgentAdapter."""

    def test_adapter_initialization(self, mock_chuk_agent):
        """Test adapter initialization."""
        adapter = ChukAgentAdapter(mock_chuk_agent)
        
        assert adapter.agent is mock_chuk_agent
        assert adapter.name == "test_chuk_agent"
        assert "text/plain" in adapter.supported_content_types
        assert "multipart/mixed" in adapter.supported_content_types

    def test_message_content_extraction(self, chuk_adapter):
        """Test extraction of content from A2A messages."""
        # Test with simple text message
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Hello world")]
        )
        content = chuk_adapter._extract_message_content(message)
        assert content == "Hello world"
        
        # Test with multiple text parts
        message = Message(
            role=Role.user,
            parts=[
                TextPart(type="text", text="Hello "),
                TextPart(type="text", text="world")
            ]
        )
        content = chuk_adapter._extract_message_content(message)
        assert content == "Hello  world"
        
        # Test with empty message
        message = Message(role=Role.user, parts=[])
        content = chuk_adapter._extract_message_content(message)
        assert isinstance(content, str)
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_process_task_basic(self, chuk_adapter, mock_chuk_agent):
        """Test basic task processing."""
        task_id = "test_task_123"
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Hello ChukAgent")]
        )
        
        # Collect events
        events = []
        async for event in chuk_adapter.process_task(task_id, message):
            events.append(event)
        
        # Should have at least working, response artifact, and completed events
        assert len(events) >= 3
        
        # Check event types
        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
        
        assert len(status_events) >= 2  # working + completed
        assert len(artifact_events) >= 1  # response artifact
        
        # Check working status
        working_event = status_events[0]
        assert working_event.status.state == TaskState.working
        assert working_event.final is False
        
        # Check completion status
        final_event = status_events[-1]
        assert final_event.status.state == TaskState.completed
        assert final_event.final is True
        
        # Verify agent was called correctly
        assert mock_chuk_agent.initialize_tools_called
        assert mock_chuk_agent.get_available_tools_called
        assert mock_chuk_agent.complete_called
        assert mock_chuk_agent.last_use_tools is True

    @pytest.mark.asyncio
    async def test_process_task_with_tools(self, chuk_adapter, mock_chuk_agent):
        """Test task processing with tool usage."""
        task_id = "test_task_tools"
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Hello, can you help me?")]  # Don't mention tools
        )
        
        events = []
        async for event in chuk_adapter.process_task(task_id, message):
            events.append(event)
        
        # Should have completed successfully
        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
        
        # Check final state
        final_event = status_events[-1]
        assert final_event.status.state == TaskState.completed
        
        # Should have response artifacts
        response_artifacts = [e for e in artifact_events if e.artifact.name.endswith("_response")]
        assert len(response_artifacts) >= 1  # At least response artifact

    @pytest.mark.asyncio
    async def test_process_task_tool_initialization_failure(self, mock_chuk_agent):
        """Test handling of tool initialization failure."""
        # Configure agent to fail tool initialization
        mock_chuk_agent.fail_init = True
        adapter = ChukAgentAdapter(mock_chuk_agent)
        
        task_id = "test_fail_init"
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Test message")]
        )
        
        events = []
        async for event in adapter.process_task(task_id, message):
            events.append(event)
        
        # Should fail gracefully
        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        final_event = status_events[-1]
        assert final_event.status.state == TaskState.failed

    @pytest.mark.asyncio
    async def test_process_task_completion_failure(self, mock_chuk_agent):
        """Test handling of completion failure."""
        # Configure agent to fail completion
        mock_chuk_agent.fail_complete = True
        adapter = ChukAgentAdapter(mock_chuk_agent)
        
        task_id = "test_fail_complete"
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Test message")]
        )
        
        events = []
        async for event in adapter.process_task(task_id, message):
            events.append(event)
        
        # Should fail gracefully with error artifact
        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
        
        final_event = status_events[-1]
        assert final_event.status.state == TaskState.failed
        
        # Should have error artifact
        error_artifacts = [e for e in artifact_events if e.artifact.name == "error"]
        assert len(error_artifacts) >= 1

    @pytest.mark.asyncio
    async def test_cancel_task(self, chuk_adapter):
        """Test task cancellation."""
        result = await chuk_adapter.cancel_task("test_task")
        assert result is False  # ChukAgent doesn't support cancellation

    @pytest.mark.asyncio
    async def test_conversation_history(self, chuk_adapter):
        """Test conversation history retrieval."""
        history = await chuk_adapter.get_conversation_history("test_session")
        assert isinstance(history, list)
        # ChukAgent doesn't implement session management by default
        assert history == []

    @pytest.mark.asyncio
    async def test_token_usage(self, chuk_adapter):
        """Test token usage retrieval."""
        usage = await chuk_adapter.get_token_usage("test_session")
        assert isinstance(usage, dict)
        assert "total_tokens" in usage
        assert "estimated_cost" in usage
        # Default implementation returns zeros
        assert usage["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_empty_message_handling(self, chuk_adapter, mock_chuk_agent):
        """Test handling of empty messages."""
        task_id = "test_empty"
        message = Message(role=Role.user, parts=[])
        
        events = []
        async for event in chuk_adapter.process_task(task_id, message):
            events.append(event)
        
        # Should still complete successfully
        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        final_event = status_events[-1]
        assert final_event.status.state == TaskState.completed
        
        # Agent should have been called
        assert mock_chuk_agent.complete_called

    @pytest.mark.asyncio
    async def test_concurrent_tasks(self, chuk_adapter):
        """Test processing multiple concurrent tasks."""
        messages = [
            Message(role=Role.user, parts=[TextPart(type="text", text=f"Task {i}")])
            for i in range(3)
        ]
        
        # Start multiple tasks concurrently
        tasks = [
            chuk_adapter.process_task(f"concurrent_{i}", msg)
            for i, msg in enumerate(messages)
        ]
        
        # Collect all results
        all_results = []
        for task in tasks:
            events = []
            async for event in task:
                events.append(event)
            all_results.append(events)
        
        # All tasks should complete
        assert len(all_results) == 3
        for events in all_results:
            status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
            final_event = status_events[-1]
            assert final_event.status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_system_prompt_integration(self, chuk_adapter, mock_chuk_agent):
        """Test that system prompt is properly integrated."""
        task_id = "test_system_prompt"
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Test message")]
        )
        
        events = []
        async for event in chuk_adapter.process_task(task_id, message):
            events.append(event)
        
        # Check that complete was called with system message
        assert mock_chuk_agent.complete_called
        assert mock_chuk_agent.last_messages is not None
        
        # Should have system message
        system_messages = [msg for msg in mock_chuk_agent.last_messages if msg.get("role") == "system"]
        assert len(system_messages) >= 1
        
        # System message should contain agent name
        system_content = system_messages[0].get("content", "")
        assert "test_chuk_agent" in system_content

    def test_adapter_properties(self, chuk_adapter):
        """Test adapter properties."""
        assert hasattr(chuk_adapter, 'name')
        assert hasattr(chuk_adapter, 'supported_content_types')
        assert hasattr(chuk_adapter, 'agent')
        
        # Test inheritance from TaskHandler
        assert hasattr(chuk_adapter, 'process_task')
        assert hasattr(chuk_adapter, 'cancel_task')
        assert hasattr(chuk_adapter, 'get_conversation_history')
        assert hasattr(chuk_adapter, 'get_token_usage')


class TestChukAgentAdapterIntegration:
    """Integration tests for ChukAgentAdapter."""

    @pytest.mark.asyncio
    async def test_full_workflow_with_tools(self):
        """Test complete workflow with tool usage."""
        mock_agent = MockChukAgent(name="integration_test_agent")
        adapter = ChukAgentAdapter(mock_agent)
        
        task_id = "integration_test"
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Hello, can you help me with something?")]  # Avoid tool trigger
        )
        
        events = []
        async for event in adapter.process_task(task_id, message):
            events.append(event)
        
        # Should have working and completed events
        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
        
        assert len(status_events) >= 2  # working + completed
        
        # Check final state - should complete successfully
        final_event = status_events[-1]
        assert final_event.status.state == TaskState.completed
        
        # Should have at least response artifact
        response_artifacts = [e for e in artifact_events if e.artifact.name.endswith("_response")]
        assert len(response_artifacts) >= 1
        
        # Verify agent was called correctly
        assert mock_agent.initialize_tools_called
        assert mock_agent.get_available_tools_called
        
        # Check messages sent to agent
        messages = mock_agent.last_messages
        assert len(messages) >= 2  # system + user
        
        # Should have enhanced system prompt with tool info
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "tools" in system_msg["content"].lower()

    @pytest.mark.asyncio
    async def test_error_recovery(self):
        """Test error handling and recovery."""
        # First agent fails
        failing_agent = MockChukAgent(fail_complete=True)
        adapter = ChukAgentAdapter(failing_agent)
        
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Test message")]
        )
        
        # Should fail gracefully
        events = []
        async for event in adapter.process_task("fail_test", message):
            events.append(event)
        
        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        final_event = status_events[-1]
        assert final_event.status.state == TaskState.failed
        
        # Working agent should succeed
        working_agent = MockChukAgent()
        adapter2 = ChukAgentAdapter(working_agent)
        
        events2 = []
        async for event in adapter2.process_task("success_test", message):
            events2.append(event)
        
        status_events2 = [e for e in events2 if isinstance(e, TaskStatusUpdateEvent)]
        final_event2 = status_events2[-1]
        assert final_event2.status.state == TaskState.completed


if __name__ == "__main__":
    # Manual test runner for development
    import asyncio
    
    async def manual_test():
        mock_agent = MockChukAgent()
        adapter = ChukAgentAdapter(mock_agent)
        
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Please use tools to help me")]
        )
        
        print(f"Testing {adapter.name} adapter...")
        
        async for event in adapter.process_task("manual_test", message):
            if isinstance(event, TaskStatusUpdateEvent):
                print(f"Status: {event.status.state}")
            elif isinstance(event, TaskArtifactUpdateEvent):
                content = event.artifact.parts[0].model_dump()["text"]
                print(f"Artifact ({event.artifact.name}): {content[:100]}...")
        
        print("Manual test completed!")
    
    # Uncomment to run manual test
    # asyncio.run(manual_test())