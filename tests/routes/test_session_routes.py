#!/usr/bin/env python3
# tests/routes/test_session_routes.py
import json
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Mock the problematic import before importing the module
mock_session_aware = MagicMock()
mock_session_aware.SessionAwareTaskHandler = type('SessionAwareTaskHandler', (), {})

# Create the mock module structure
sys.modules['a2a_server.tasks.handlers.adk'] = MagicMock()
sys.modules['a2a_server.tasks.handlers.adk.session_enabled_adk_handler'] = mock_session_aware

# Now we can safely import
from a2a_server.routes.session_routes import register_session_routes


class MockSessionStore:
    """Mock for the session store."""
    
    async def list_sessions(self):
        return ["session1", "session2", "session3"]


class MockSessionAwareHandler(mock_session_aware.SessionAwareTaskHandler):
    """Mock implementation of SessionAwareTaskHandler for testing."""
    
    def __init__(self, name):
        super().__init__()
        self._name = name
        self._session_map = {
            "a2a_session_1": "chuk_session_1",
            "a2a_session_2": "chuk_session_2",
        }
        
    @property
    def name(self):
        return self._name
        
    async def process_task(self, task_id, message, session_id=None):
        yield None  # Not used in tests
        
    async def get_conversation_history(self, session_id=None):
        if session_id == "a2a_session_1":
            return [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ]
        return []
        
    async def get_token_usage(self, session_id=None):
        if session_id == "a2a_session_1":
            return {
                "total_tokens": 100,
                "total_cost_usd": 0.002,
                "by_model": {
                    "gpt-3.5-turbo": {
                        "prompt_tokens": 50,
                        "completion_tokens": 50,
                        "total_tokens": 100,
                        "cost_usd": 0.002
                    }
                }
            }
        return {"total_tokens": 0, "total_cost_usd": 0}


class MockRegularHandler:
    """Mock handler that doesn't support sessions."""
    
    def __init__(self, name):
        self._name = name
    
    @property
    def name(self):
        return self._name


class MockTaskManager:
    """Mock TaskManager for testing."""
    
    def __init__(self):
        self._handlers = {
            "session_handler": MockSessionAwareHandler("session_handler"),
            "regular_handler": MockRegularHandler("regular_handler"),
        }
        
    def get_handlers(self):
        return {"session_handler": "session_handler", "regular_handler": "regular_handler"}
        
    def get_default_handler(self):
        return "session_handler"


@pytest.fixture
def app():
    """Create a test FastAPI app with session routes registered."""
    app = FastAPI()
    register_session_routes(app)
    
    # Set up app state with mocks
    app.state.task_manager = MockTaskManager()
    app.state.session_store = MockSessionStore()
    
    return app


@pytest.fixture
def client(app):
    """Create a TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def admin_headers():
    """Headers with admin token for authenticated requests."""
    return {"X-A2A-Admin-Token": "test-token"}


def test_routes_disabled_by_env_var():
    """Test that session routes can be disabled via environment variable."""
    with patch.dict("os.environ", {"A2A_DISABLE_SESSION_ROUTES": "1"}):
        app = FastAPI()
        register_session_routes(app)
        
        client = TestClient(app)
        response = client.get("/sessions")
        assert response.status_code == 404  # Route not registered


class TestAuthGuard:
    """Test the admin authentication guard."""
    
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_admin_token(self, client):
        """Test that requests without admin token are accepted when no token set."""
        response = client.get("/sessions")
        assert response.status_code == 200
    
    @patch.dict("os.environ", {"A2A_ADMIN_TOKEN": "secret123"}, clear=False)
    def test_wrong_admin_token(self, client):
        """Test that requests with wrong admin token are rejected."""
        headers = {"X-A2A-Admin-Token": "wrong-token"}
        response = client.get("/sessions", headers=headers)
        assert response.status_code == 401
    
    @patch.dict("os.environ", {"A2A_ADMIN_TOKEN": "secret123"}, clear=False)
    def test_correct_admin_token(self, client):
        """Test that requests with correct admin token are accepted."""
        headers = {"X-A2A-Admin-Token": "secret123"}
        response = client.get("/sessions", headers=headers)
        assert response.status_code == 200
    
    @patch.dict("os.environ", {}, clear=True)
    def test_no_token_env_allows_access(self, client):
        """Test that when no token is set, access is allowed."""
        response = client.get("/sessions")
        assert response.status_code == 200


class TestListSessions:
    """Test the list sessions endpoint."""
    
    @patch.dict("os.environ", {}, clear=True)
    def test_list_sessions_success(self, client):
        """Test listing sessions endpoint."""
        response = client.get("/sessions")
        assert response.status_code == 200
        
        data = response.json()
        assert "handlers_with_sessions" in data
        assert "total_sessions_in_store" in data
        assert data["total_sessions_in_store"] == 3
        
        # Check that we got session data for the session-aware handler
        handlers = data["handlers_with_sessions"]
        assert "session_handler" in handlers
        assert len(handlers["session_handler"]) == 2
        
        # Verify session mapping data
        sessions = handlers["session_handler"]
        assert {"a2a_session_id": "a2a_session_1", "chuk_session_id": "chuk_session_1"} in sessions
        assert {"a2a_session_id": "a2a_session_2", "chuk_session_id": "chuk_session_2"} in sessions
    
    @patch.dict("os.environ", {}, clear=True)
    def test_list_sessions_no_session_handlers(self, client, app):
        """Test listing sessions when no handlers support sessions."""
        # Replace with task manager that has no session-aware handlers
        app.state.task_manager._handlers = {
            "regular_handler": MockRegularHandler("regular_handler")
        }
        # Update get_handlers to reflect the change
        app.state.task_manager.get_handlers = lambda: {"regular_handler": "regular_handler"}
        
        response = client.get("/sessions")
        assert response.status_code == 200
        
        data = response.json()
        assert data["handlers_with_sessions"] == {}
        assert data["total_sessions_in_store"] == 3


class TestGetSessionHistory:
    """Test the get session history endpoint."""
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_session_history_success(self, client):
        """Test getting session history."""
        response = client.get("/sessions/a2a_session_1/history")
        assert response.status_code == 200
        
        data = response.json()
        assert data["session_id"] == "a2a_session_1"
        assert data["handler"] == "session_handler"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_session_history_empty(self, client):
        """Test getting history for session with no messages."""
        response = client.get("/sessions/nonexistent/history")
        assert response.status_code == 200
        
        data = response.json()
        assert data["session_id"] == "nonexistent"
        assert len(data["messages"]) == 0
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_session_history_with_specific_handler(self, client):
        """Test getting session history with explicit handler specified."""
        response = client.get("/sessions/a2a_session_1/history?handler_name=session_handler")
        assert response.status_code == 200
        
        data = response.json()
        assert data["handler"] == "session_handler"
        assert len(data["messages"]) == 2
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_session_history_with_invalid_handler(self, client):
        """Test getting session history with non-existent handler."""
        response = client.get("/sessions/a2a_session_1/history?handler_name=nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_session_history_with_non_session_handler(self, client):
        """Test getting session history with a handler that doesn't support sessions."""
        response = client.get("/sessions/a2a_session_1/history?handler_name=regular_handler")
        assert response.status_code == 400
        assert "does not support sessions" in response.json()["detail"]


class TestGetTokenUsage:
    """Test the get token usage endpoint."""
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_token_usage_success(self, client):
        """Test getting token usage statistics."""
        response = client.get("/sessions/a2a_session_1/tokens")
        assert response.status_code == 200
        
        data = response.json()
        assert data["session_id"] == "a2a_session_1"
        assert data["handler"] == "session_handler"
        assert data["token_usage"]["total_tokens"] == 100
        assert data["token_usage"]["total_cost_usd"] == 0.002
        assert "gpt-3.5-turbo" in data["token_usage"]["by_model"]
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_token_usage_empty(self, client):
        """Test getting token usage for session with no usage."""
        response = client.get("/sessions/nonexistent/tokens")
        assert response.status_code == 200
        
        data = response.json()
        assert data["token_usage"]["total_tokens"] == 0
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_token_usage_with_specific_handler(self, client):
        """Test getting token usage with explicit handler specified."""
        response = client.get("/sessions/a2a_session_1/tokens?handler_name=session_handler")
        assert response.status_code == 200
        
        data = response.json()
        assert data["handler"] == "session_handler"
        assert data["token_usage"]["total_tokens"] == 100
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_token_usage_with_invalid_handler(self, client):
        """Test getting token usage with non-existent handler."""
        response = client.get("/sessions/a2a_session_1/tokens?handler_name=nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    @patch.dict("os.environ", {}, clear=True)
    def test_get_token_usage_with_non_session_handler(self, client):
        """Test getting token usage with a handler that doesn't support sessions."""
        response = client.get("/sessions/a2a_session_1/tokens?handler_name=regular_handler")
        assert response.status_code == 400
        assert "does not support sessions" in response.json()["detail"]


class TestHelperFunctions:
    """Test the helper functions used by the routes."""
    
    @patch.dict("os.environ", {}, clear=True)
    def test_resolve_handler_default(self, client, app):
        """Test resolving the default handler."""
        task_manager = app.state.task_manager
        
        from a2a_server.routes.session_routes import _resolve_handler
        
        handler = _resolve_handler(task_manager, None)
        assert handler.name == "session_handler"
    
    @patch.dict("os.environ", {}, clear=True)
    def test_resolve_handler_by_name(self, client, app):
        """Test resolving handler by name."""
        task_manager = app.state.task_manager
        
        from a2a_server.routes.session_routes import _resolve_handler
        
        handler = _resolve_handler(task_manager, "session_handler")
        assert handler.name == "session_handler"
    
    @patch.dict("os.environ", {}, clear=True)
    def test_resolve_handler_not_found(self, client, app):
        """Test resolving non-existent handler."""
        task_manager = app.state.task_manager
        
        from a2a_server.routes.session_routes import _resolve_handler
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            _resolve_handler(task_manager, "nonexistent")
        
        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value.detail)
    
    @patch.dict("os.environ", {}, clear=True)
    def test_resolve_handler_no_default(self, client, app):
        """Test resolving when no default handler is configured."""
        task_manager = app.state.task_manager
        original_get_default = task_manager.get_default_handler
        task_manager.get_default_handler = lambda: None
        
        from a2a_server.routes.session_routes import _resolve_handler
        from fastapi import HTTPException
        
        try:
            with pytest.raises(HTTPException) as exc_info:
                _resolve_handler(task_manager, None)
            
            assert exc_info.value.status_code == 404
            assert "No default handler configured" in str(exc_info.value.detail)
        finally:
            task_manager.get_default_handler = original_get_default
    
    @patch.dict("os.environ", {}, clear=True) 
    def test_ensure_session_capable(self, client, app):
        """Test ensuring handler supports sessions."""
        from a2a_server.routes.session_routes import _ensure_session_capable
        from fastapi import HTTPException
        
        # Test with session-aware handler - should not raise
        session_handler = app.state.task_manager._handlers["session_handler"]
        _ensure_session_capable(session_handler)  # Should not raise
        
        # Test with regular handler - should raise
        regular_handler = app.state.task_manager._handlers["regular_handler"]
        
        with pytest.raises(HTTPException) as exc_info:
            _ensure_session_capable(regular_handler)
        
        assert exc_info.value.status_code == 400
        assert "does not support sessions" in str(exc_info.value.detail)


class TestRouteExclusion:
    """Test that routes are properly excluded from OpenAPI schema."""
    
    def test_session_routes_not_in_schema(self, app):
        """Verify session routes are excluded from OpenAPI schema."""
        openapi_schema = app.openapi()
        paths = openapi_schema.get("paths", {})
        
        # Session routes should not appear in the schema
        assert "/sessions" not in paths
        assert "/sessions/{session_id}/history" not in paths
        assert "/sessions/{session_id}/tokens" not in paths


class TestErrorHandling:
    """Test error handling in session routes."""
    
    @patch.dict("os.environ", {}, clear=True)
    def test_session_store_error(self, client, app):
        """Test handling of session store errors."""
        # Mock the session store to raise an error
        async def failing_list_sessions():
            raise Exception("Session store error")
        
        app.state.session_store.list_sessions = failing_list_sessions
        
        response = client.get("/sessions")
        # The route should still work but session count will be 0
        assert response.status_code == 200
        data = response.json()
        assert data["total_sessions_in_store"] == 0  # Error handled gracefully
    
    @patch.dict("os.environ", {}, clear=True)
    def test_handler_error(self, client, app):
        """Test handling of handler errors."""
        # Mock the handler to raise an error
        async def failing_get_conversation_history(session_id):
            raise Exception("Handler error")
        
        handler = app.state.task_manager._handlers["session_handler"]
        original_method = handler.get_conversation_history
        handler.get_conversation_history = failing_get_conversation_history
        
        try:
            response = client.get("/sessions/test/history")
            # The exception propagates and causes a 500 error in real scenarios
            # but the test client might handle it differently
            assert response.status_code in [400, 500]  # Either is acceptable
        finally:
            handler.get_conversation_history = original_method


@pytest.mark.asyncio
class TestAsyncFunctionality:
    """Test async aspects of session routes."""
    
    async def test_async_session_operations(self):
        """Test that session operations work asynchronously."""
        handler = MockSessionAwareHandler("test")
        
        # Test async methods
        history = await handler.get_conversation_history("a2a_session_1")
        assert len(history) == 2
        
        usage = await handler.get_token_usage("a2a_session_1")
        assert usage["total_tokens"] == 100
        
        empty_history = await handler.get_conversation_history("nonexistent")
        assert len(empty_history) == 0