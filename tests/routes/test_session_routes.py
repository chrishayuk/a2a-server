# #!/usr/bin/env python3
# # tests/routes/test_session_routes.py
# import json
# import pytest
# from unittest.mock import AsyncMock, MagicMock, patch
# from fastapi import FastAPI
# from fastapi.testclient import TestClient

# from a2a_server.routes.session_routes import register_session_routes
# from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler


# class MockSessionStore:
#     """Mock for the session store."""
    
#     async def list_sessions(self):
#         return ["session1", "session2", "session3"]


# class MockSessionAwareHandler(SessionAwareTaskHandler):
#     """Mock implementation of SessionAwareTaskHandler for testing."""
    
#     def __init__(self, name):
#         self._name = name
#         self._session_map = {
#             "a2a_session_1": "chuk_session_1",
#             "a2a_session_2": "chuk_session_2",
#         }
        
#     @property
#     def name(self):
#         return self._name
        
#     async def process_task(self, task_id, message, session_id=None):
#         yield None  # Not used in tests
        
#     async def get_conversation_history(self, session_id=None):
#         if session_id == "a2a_session_1":
#             return [
#                 {"role": "user", "content": "Hello"},
#                 {"role": "assistant", "content": "Hi there!"},
#             ]
#         return []
        
#     async def get_token_usage(self, session_id=None):
#         if session_id == "a2a_session_1":
#             return {
#                 "total_tokens": 100,
#                 "total_cost_usd": 0.002,
#                 "by_model": {
#                     "gpt-3.5-turbo": {
#                         "prompt_tokens": 50,
#                         "completion_tokens": 50,
#                         "total_tokens": 100,
#                         "cost_usd": 0.002
#                     }
#                 }
#             }
#         return {"total_tokens": 0, "total_cost_usd": 0}
        
#     async def _llm_call(self, messages, model="default"):
#         return "Test summary"  # Not used in tests


# class MockTaskManager:
#     """Mock TaskManager for testing."""
    
#     def __init__(self):
#         self._handlers = {
#             "session_handler": MockSessionAwareHandler("session_handler"),
#             "regular_handler": MagicMock(name="regular_handler"),
#         }
        
#     def get_handlers(self):
#         return {"session_handler": "session_handler", "regular_handler": "regular_handler"}
        
#     def get_default_handler(self):
#         return "session_handler"


# @pytest.fixture
# def app():
#     """Create a test FastAPI app with session routes registered."""
#     app = FastAPI()
#     register_session_routes(app)
    
#     # Set up app state with mocks
#     app.state.task_manager = MockTaskManager()
#     app.state.session_store = MockSessionStore()
    
#     return app


# @pytest.fixture
# def client(app):
#     """Create a TestClient for the app."""
#     return TestClient(app)


# def test_list_sessions(client):
#     """Test listing sessions endpoint."""
#     response = client.get("/sessions")
#     assert response.status_code == 200
    
#     data = response.json()
#     assert "handlers_with_sessions" in data
#     assert "total_sessions_in_store" in data
#     assert data["total_sessions_in_store"] == 3
    
#     # Check that we got session data for the session-aware handler
#     handlers = data["handlers_with_sessions"]
#     assert "session_handler" in handlers
#     assert len(handlers["session_handler"]) == 2
    
#     # Verify session mapping data
#     sessions = handlers["session_handler"]
#     assert {"a2a_session_id": "a2a_session_1", "chuk_session_id": "chuk_session_1"} in sessions
#     assert {"a2a_session_id": "a2a_session_2", "chuk_session_id": "chuk_session_2"} in sessions


# def test_get_session_history(client):
#     """Test getting session history."""
#     # Test with valid session ID
#     response = client.get("/sessions/a2a_session_1/history")
#     assert response.status_code == 200
    
#     data = response.json()
#     assert data["session_id"] == "a2a_session_1"
#     assert data["handler"] == "session_handler"
#     assert len(data["messages"]) == 2
#     assert data["messages"][0]["role"] == "user"
#     assert data["messages"][1]["role"] == "assistant"
    
#     # Test with invalid session ID
#     response = client.get("/sessions/nonexistent/history")
#     assert response.status_code == 200  # It still returns successfully but with empty messages
#     assert len(response.json()["messages"]) == 0


# def test_get_session_history_with_specific_handler(client):
#     """Test getting session history with explicit handler specified."""
#     response = client.get("/sessions/a2a_session_1/history?handler_name=session_handler")
#     assert response.status_code == 200
    
#     data = response.json()
#     assert data["handler"] == "session_handler"
#     assert len(data["messages"]) == 2


# def test_get_session_history_with_invalid_handler(client):
#     """Test getting session history with non-existent handler."""
#     response = client.get("/sessions/a2a_session_1/history?handler_name=nonexistent")
#     assert response.status_code == 404
#     assert "not found" in response.json()["detail"]


# def test_get_session_history_with_non_session_handler(client):
#     """Test getting session history with a handler that doesn't support sessions."""
#     response = client.get("/sessions/a2a_session_1/history?handler_name=regular_handler")
#     assert response.status_code == 400
#     assert "does not support sessions" in response.json()["detail"]


# def test_get_token_usage(client):
#     """Test getting token usage statistics."""
#     # Test with valid session ID
#     response = client.get("/sessions/a2a_session_1/tokens")
#     assert response.status_code == 200
    
#     data = response.json()
#     assert data["session_id"] == "a2a_session_1"
#     assert data["handler"] == "session_handler"
#     assert data["token_usage"]["total_tokens"] == 100
#     assert data["token_usage"]["total_cost_usd"] == 0.002
#     assert "gpt-3.5-turbo" in data["token_usage"]["by_model"]
    
#     # Test with invalid session ID
#     response = client.get("/sessions/nonexistent/tokens")
#     assert response.status_code == 200  # It still returns successfully but with zero tokens
#     assert response.json()["token_usage"]["total_tokens"] == 0


# def test_get_token_usage_with_specific_handler(client):
#     """Test getting token usage with explicit handler specified."""
#     response = client.get("/sessions/a2a_session_1/tokens?handler_name=session_handler")
#     assert response.status_code == 200
    
#     data = response.json()
#     assert data["handler"] == "session_handler"
#     assert data["token_usage"]["total_tokens"] == 100


# def test_get_token_usage_with_invalid_handler(client):
#     """Test getting token usage with non-existent handler."""
#     response = client.get("/sessions/a2a_session_1/tokens?handler_name=nonexistent")
#     assert response.status_code == 404
#     assert "not found" in response.json()["detail"]


# def test_get_token_usage_with_non_session_handler(client):
#     """Test getting token usage with a handler that doesn't support sessions."""
#     response = client.get("/sessions/a2a_session_1/tokens?handler_name=regular_handler")
#     assert response.status_code == 400
#     assert "does not support sessions" in response.json()["detail"]