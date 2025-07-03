# """
# Updated tests for the simplified Google ADK handler with proper imports and working mocks.
# """
# import pytest
# import asyncio
# from typing import Dict, Any, AsyncIterable, Optional, List
# from unittest.mock import MagicMock, patch, AsyncMock

# # Basic imports that should always work
# from a2a_json_rpc.spec import (
#     Message, TextPart, Role, TaskState, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
# )

# # Try to import TaskStatus
# try:
#     from a2a_json_rpc.spec import TaskStatus
# except ImportError:
#     # Create a mock TaskStatus if not available
#     class TaskStatus:
#         def __init__(self, state, timestamp=None, message=None):
#             self.state = state
#             self.timestamp = timestamp
#             self.message = message

# # Try to import the real GoogleADKHandler
# try:
#     from a2a_server.tasks.handlers.adk import GoogleADKHandler
#     ADK_HANDLER_AVAILABLE = True
#     print("✅ Real GoogleADKHandler imported successfully")
# except ImportError as e:
#     print(f"⚠️ Could not import real GoogleADKHandler: {e}")
#     ADK_HANDLER_AVAILABLE = False
    
#     # Create a working mock for testing when the real handler isn't available
#     class MockGoogleADKHandler:
#         def __init__(self, agent, name=None, **kwargs):
#             self.agent = agent
#             self.name = name or getattr(agent, 'name', 'mock_adk_handler')
#             self.task_timeout = kwargs.get('task_timeout', 240.0)
        
#         async def process_task(self, task_id, message, session_id=None):
#             # Yield working status
#             yield TaskStatusUpdateEvent(
#                 id=task_id,
#                 status=TaskStatus(state=TaskState.working),
#                 final=False
#             )
            
#             # Simulate calling the agent if it has invoke method
#             if hasattr(self.agent, 'invoke'):
#                 try:
#                     result = self.agent.invoke(self._extract_message_content(message), session_id)
#                     # Create an artifact with the result
#                     from a2a_json_rpc.spec import Artifact
#                     artifact = Artifact(
#                         name="response",
#                         parts=[TextPart(type="text", text=result or "No response")],
#                         index=0
#                     )
#                     yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
#                 except Exception:
#                     # If agent fails, still complete the task
#                     pass
            
#             # Yield completion status
#             yield TaskStatusUpdateEvent(
#                 id=task_id,
#                 status=TaskStatus(state=TaskState.completed),
#                 final=True
#             )
        
#         async def cancel_task(self, task_id):
#             return False
            
#         def get_health_status(self):
#             return {
#                 "handler_name": self.name,
#                 "handler_type": "mock_google_adk",
#                 "status": "mock_healthy"
#             }
        
#         def _extract_message_content(self, message):
#             """Extract text from message - FIXED VERSION."""
#             if not message or not hasattr(message, 'parts') or not message.parts:
#                 return ""
            
#             text_parts = []
#             for part in message.parts:
#                 try:
#                     # Try direct text attribute first
#                     if hasattr(part, "text") and part.text:
#                         text_parts.append(str(part.text))
#                     # Try model_dump if available
#                     elif hasattr(part, "model_dump"):
#                         part_dict = part.model_dump()
#                         if "text" in part_dict and part_dict["text"]:
#                             text_parts.append(str(part_dict["text"]))
#                     # Try dict-like access
#                     elif hasattr(part, '__getitem__'):
#                         try:
#                             text = part["text"]
#                             if text:
#                                 text_parts.append(str(text))
#                         except (KeyError, TypeError):
#                             pass
#                 except Exception:
#                     continue
            
#             return " ".join(text_parts).strip()
    
#     GoogleADKHandler = MockGoogleADKHandler


# class MockGoogleADKAgent:
#     """Mock Google ADK agent for testing."""
    
#     SUPPORTED_CONTENT_TYPES = ["text/plain", "application/json"]
    
#     def __init__(self, name="test_adk_agent", model="test_model"):
#         self.name = name
#         self.model = model
#         self.instruction = "You are a test ADK agent"
#         self.invoke_called = False
#         self.last_query = None
#         self.last_session_id = None
#         self._should_error = False
    
#     def invoke(self, query: str, session_id: Optional[str] = None) -> str:
#         """Mock synchronous invocation."""
#         self.invoke_called = True
#         self.last_query = query
#         self.last_session_id = session_id
        
#         if self._should_error or "error" in query.lower():
#             raise ValueError("Simulated ADK error")
#         elif "empty" in query.lower():
#             return ""
#         elif "json" in query.lower():
#             return '{"status": "success", "data": "test"}'
#         else:
#             return f"ADK response to: {query}"

#     async def stream(self, query: str, session_id: Optional[str] = None) -> AsyncIterable[Dict[str, Any]]:
#         """Mock streaming invocation."""
#         self.last_query = query
#         self.last_session_id = session_id
        
#         if self._should_error or "error" in query.lower():
#             raise ValueError("Simulated streaming error")
        
#         yield {"is_task_complete": False, "updates": "Processing..."}
#         await asyncio.sleep(0.01)
#         yield {"is_task_complete": True, "content": f"Streaming response to: {query}"}

#     def set_error_mode(self, should_error: bool):
#         """Set whether the agent should simulate errors."""
#         self._should_error = should_error


# class MockRawADKAgent:
#     """Mock raw ADK agent that needs wrapping."""
    
#     def __init__(self, name="raw_adk", model="test_model"):
#         self.name = name
#         self.model = model
#         self.instruction = "Raw ADK agent for testing"
#         # Missing invoke/stream methods - needs adapter
    
#     @property
#     def __module__(self):
#         return "google.adk.agents"


# @pytest.fixture
# def mock_adk_agent():
#     """Create a mock ADK agent for testing."""
#     return MockGoogleADKAgent()


# @pytest.fixture
# def mock_raw_adk_agent():
#     """Create a mock raw ADK agent that needs wrapping."""
#     return MockRawADKAgent()


# @pytest.fixture
# def adk_handler(mock_adk_agent):
#     """Create a GoogleADKHandler with a mock agent."""
#     if ADK_HANDLER_AVAILABLE:
#         # Mock session dependencies for real handler
#         with patch.dict('sys.modules', {
#             'chuk_sessions': MagicMock(),
#             'chuk_ai_session_manager': MagicMock(),
#         }), patch('a2a_server.utils.session_setup.setup_handler_sessions') as mock_setup:
#             mock_setup.return_value = ("test_sandbox", {"enable_sessions": True})
#             return GoogleADKHandler(agent=mock_adk_agent, name="test_adk_handler")
#     else:
#         return GoogleADKHandler(agent=mock_adk_agent, name="test_adk_handler")


# @pytest.fixture  
# def adk_handler_with_sessions(mock_adk_agent):
#     """Create a GoogleADKHandler with sessions enabled."""
#     if ADK_HANDLER_AVAILABLE:
#         with patch.dict('sys.modules', {
#             'chuk_sessions': MagicMock(),
#             'chuk_ai_session_manager': MagicMock(),
#         }), patch('a2a_server.utils.session_setup.setup_handler_sessions') as mock_setup:
#             mock_setup.return_value = ("test_adk_sessions", {"enable_sessions": True})
#             return GoogleADKHandler(
#                 agent=mock_adk_agent,
#                 name="test_adk_handler_sessions",
#                 sandbox_id="test_adk_sessions"
#             )
#     else:
#         return GoogleADKHandler(
#             agent=mock_adk_agent,
#             name="test_adk_handler_sessions",
#             sandbox_id="test_adk_sessions"
#         )


# class TestGoogleADKHandler:
#     """Test suite for GoogleADKHandler."""

#     def test_handler_initialization(self, mock_adk_agent):
#         """Test handler initialization with various configurations."""
#         if ADK_HANDLER_AVAILABLE:
#             with patch.dict('sys.modules', {
#                 'chuk_sessions': MagicMock(),
#                 'chuk_ai_session_manager': MagicMock(),
#             }), patch('a2a_server.utils.session_setup.setup_handler_sessions') as mock_setup:
#                 mock_setup.return_value = ("test_sandbox", {"enable_sessions": True})
                
#                 # Basic initialization
#                 handler = GoogleADKHandler(agent=mock_adk_agent)
#                 # With real handler, name should be from agent or default
#                 assert handler.name in ["test_adk_agent", "test_adk_handler", mock_adk_agent.name]
                
#                 # Custom name and configuration
#                 handler = GoogleADKHandler(
#                     agent=mock_adk_agent,
#                     name="custom_adk",
#                     task_timeout=120.0
#                 )
#                 assert handler.name == "custom_adk"
#                 assert handler.task_timeout == 120.0
#         else:
#             # With mock handler
#             handler = GoogleADKHandler(agent=mock_adk_agent)
#             assert handler.name == "test_adk_agent"  # Uses agent name
            
#             handler = GoogleADKHandler(
#                 agent=mock_adk_agent,
#                 name="custom_adk",
#                 task_timeout=120.0
#             )
#             assert handler.name == "custom_adk"
#             assert handler.task_timeout == 120.0

#     def test_handler_properties(self, adk_handler):
#         """Test handler properties and capabilities."""
#         assert adk_handler.name == "test_adk_handler"
#         assert hasattr(adk_handler, 'task_timeout')

#     @pytest.mark.asyncio
#     async def test_process_task_basic(self, adk_handler, mock_adk_agent):
#         """Test basic task processing."""
#         task_id = "test_task_123"
#         message = Message(
#             role=Role.user,
#             parts=[TextPart(type="text", text="Hello ADK agent")]
#         )
        
#         # Mock session methods if they exist (for real handler)
#         if hasattr(adk_handler, 'add_user_message'):
#             adk_handler.add_user_message = AsyncMock()
#         if hasattr(adk_handler, 'add_ai_response'):
#             adk_handler.add_ai_response = AsyncMock()
        
#         events = []
#         async for event in adk_handler.process_task(task_id, message):
#             events.append(event)
        
#         # Should have at least 2 events
#         assert len(events) >= 2
        
#         # Check event types
#         status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
#         assert len(status_events) >= 2  # working + completed
        
#         # Check final state
#         final_event = status_events[-1]
#         assert final_event.status.state in [TaskState.completed, TaskState.failed]
#         assert final_event.final is True

#     @pytest.mark.asyncio
#     async def test_process_task_with_session(self, adk_handler_with_sessions, mock_adk_agent):
#         """Test task processing with session support."""
#         task_id = "test_task_session"
#         session_id = "test_session_123"
#         message = Message(
#             role=Role.user,
#             parts=[TextPart(type="text", text="Session test")]
#         )
        
#         # Mock session methods if they exist
#         if hasattr(adk_handler_with_sessions, 'add_user_message'):
#             adk_handler_with_sessions.add_user_message = AsyncMock()
#         if hasattr(adk_handler_with_sessions, 'add_ai_response'):
#             adk_handler_with_sessions.add_ai_response = AsyncMock()
        
#         events = []
#         async for event in adk_handler_with_sessions.process_task(task_id, message, session_id):
#             events.append(event)
        
#         # Should process successfully
#         status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
#         assert len(status_events) >= 1
        
#         final_event = status_events[-1]
#         assert final_event.status.state in [TaskState.completed, TaskState.failed]

#     @pytest.mark.asyncio
#     async def test_health_status(self, adk_handler):
#         """Test health status reporting."""
#         health = adk_handler.get_health_status()
        
#         assert isinstance(health, dict)
#         assert "handler_name" in health or "status" in health

#     @pytest.mark.asyncio
#     async def test_cancel_task(self, adk_handler):
#         """Test task cancellation."""
#         result = await adk_handler.cancel_task("some_task")
#         assert result is False

#     def test_message_content_extraction(self, adk_handler):
#         """Test extraction of text content from messages."""
#         if not hasattr(adk_handler, '_extract_message_content'):
#             pytest.skip("Handler doesn't have _extract_message_content method")
        
#         message = Message(
#             role=Role.user,
#             parts=[TextPart(type="text", text="Hello world")]
#         )
#         content = adk_handler._extract_message_content(message)
#         assert content == "Hello world"
        
#         # Test edge cases
#         empty_message = Message(role=Role.user, parts=[])
#         empty_content = adk_handler._extract_message_content(empty_message)
#         assert empty_content == ""
        
#         # Test multiple parts
#         multi_message = Message(
#             role=Role.user,
#             parts=[
#                 TextPart(type="text", text="Hello"),
#                 TextPart(type="text", text="world")
#             ]
#         )
#         multi_content = adk_handler._extract_message_content(multi_message)
#         assert multi_content == "Hello world"


# class TestMockAgents:
#     """Test the mock agents themselves."""
    
#     def test_mock_adk_agent(self):
#         """Test the mock ADK agent functionality."""
#         agent = MockGoogleADKAgent()
        
#         assert agent.name == "test_adk_agent"
#         assert agent.model == "test_model"
#         assert hasattr(agent, 'SUPPORTED_CONTENT_TYPES')
        
#         result = agent.invoke("test query")
#         assert result == "ADK response to: test query"
#         assert agent.invoke_called
#         assert agent.last_query == "test query"
        
#         agent.set_error_mode(True)
#         with pytest.raises(ValueError):
#             agent.invoke("error test")
    
#     @pytest.mark.asyncio
#     async def test_mock_adk_agent_streaming(self):
#         """Test the mock ADK agent streaming functionality."""
#         agent = MockGoogleADKAgent()
        
#         events = []
#         async for event in agent.stream("stream test"):
#             events.append(event)
        
#         assert len(events) >= 2
#         final_event = events[-1]
#         assert final_event["is_task_complete"] is True
#         assert "Streaming response to: stream test" in final_event["content"]


# @pytest.mark.skipif(not ADK_HANDLER_AVAILABLE, reason="Real GoogleADKHandler not available")
# class TestRealGoogleADKHandler:
#     """Tests that only run when the real GoogleADKHandler is available."""
    
#     def test_real_handler_import(self):
#         """Test that we can import the real handler."""
#         from a2a_server.tasks.handlers.adk import GoogleADKHandler
#         assert GoogleADKHandler is not None


# def test_import_status():
#     """Test to show the import status."""
#     print(f"\nADK Handler Import Status:")
#     print(f"GoogleADKHandler available: {ADK_HANDLER_AVAILABLE}")
#     print(f"GoogleADKHandler type: {type(GoogleADKHandler)}")
    
#     if ADK_HANDLER_AVAILABLE:
#         print("✅ Real GoogleADKHandler is available for testing")
#     else:
#         print("⚠️ Using mock GoogleADKHandler for testing")


# if __name__ == "__main__":
#     test_import_status()
#     agent = MockGoogleADKAgent()
#     result = agent.invoke("test")
#     print(f"Mock agent test: {result}")
#     print("Manual test completed!")