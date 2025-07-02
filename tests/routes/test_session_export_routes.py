#!/usr/bin/env python3
# tests/routes/test_session_export_routes.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a2a_server.routes.session_export import register_session_routes


class MockHandler:
    """Mock handler that supports session operations."""
    
    def __init__(self, name, supports_sessions=True):
        self.name = name
        self._supports_sessions = supports_sessions
        
    async def list_sessions(self, detail=False):
        if detail:
            return [
                {"id": "session1", "created": "2025-01-01", "messages": 5},
                {"id": "session2", "created": "2025-01-02", "messages": 3}
            ]
        return ["session1", "session2"]
    
    async def get_conversation_history(self, session_id):
        if session_id == "session1":
            return [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "How are you?"},
                {"role": "assistant", "content": "I'm doing well, thank you!"}
            ]
        elif session_id == "session2":
            return [
                {"role": "user", "content": "What's the weather?"},
                {"role": "assistant", "content": "I don't have real-time weather data."}
            ]
        return []
    
    async def get_token_usage(self, session_id):
        if session_id == "session1":
            return {
                "total_tokens": 150,
                "total_cost_usd": 0.003,
                "by_model": {
                    "gpt-3.5-turbo": {
                        "prompt_tokens": 75,
                        "completion_tokens": 75,
                        "total_tokens": 150,
                        "cost_usd": 0.003
                    }
                }
            }
        return {"total_tokens": 0, "total_cost_usd": 0}
    
    def _get_agent_session_id(self, session_id):
        return f"agent_{session_id}"
    
    async def add_to_session(self, agent_session_id, content, is_agent=False):
        return True  # Successfully added
    
    async def delete_session(self, session_id):
        return session_id in ["session1", "session2"]


class MockInsufficientHandler:
    """Mock handler that doesn't support all session operations."""
    
    def __init__(self, name):
        self.name = name
    
    # Missing required methods for session operations


class MockTaskManager:
    """Mock TaskManager for testing."""
    
    def __init__(self):
        self._handlers = {
            "session_handler": MockHandler("session_handler"),
            "insufficient_handler": MockInsufficientHandler("insufficient_handler"),
        }
    
    def get_handlers(self):
        return {"session_handler": "session_handler", "insufficient_handler": "insufficient_handler"}
    
    def get_default_handler(self):
        return "session_handler"


@pytest.fixture
def app():
    """Create a test FastAPI app with session export routes registered."""
    app = FastAPI()
    register_session_routes(app)
    
    # Set up app state
    app.state.task_manager = MockTaskManager()
    
    return app


@pytest.fixture
def client(app):
    """Create a TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def admin_headers():
    """Headers with admin token for authenticated requests."""
    return {"X-Internal-Admin": "test-secret"}


def test_routes_disabled_by_env_var(monkeypatch):
    """Test that routes can be disabled via environment variable."""
    monkeypatch.setenv("DISABLE_SESSION_ROUTES", "1")
    app = FastAPI()
    register_session_routes(app)
    
    client = TestClient(app)
    response = client.get("/sessions")
    assert response.status_code == 404  # Route not registered


class TestAuthGuard:
    """Test the admin authentication guard."""
    
    def test_missing_admin_header(self, client):
        """Test that requests without admin header are rejected."""
        response = client.get("/sessions")
        assert response.status_code == 403
        assert "Missing X-Internal-Admin header" in response.json()["detail"]
    
    def test_wrong_admin_secret(self, client, monkeypatch):
        """Test that requests with wrong admin secret are rejected."""
        # Directly patch the os.getenv call in the module
        with patch('a2a_server.routes.session_export.os.getenv', return_value="secret123"):
            headers = {"X-Internal-Admin": "wrong-secret"}
            response = client.get("/sessions", headers=headers)
            assert response.status_code == 403
            assert "Bad admin secret" in response.json()["detail"]
    
    def test_correct_admin_secret(self, client, monkeypatch):
        """Test that requests with correct admin secret are accepted."""
        # Directly patch the os.getenv call in the module
        with patch('a2a_server.routes.session_export.os.getenv', return_value="secret123"):
            headers = {"X-Internal-Admin": "secret123"}
            response = client.get("/sessions", headers=headers)
            assert response.status_code == 200
    
    def test_no_secret_env_allows_any_header(self, client, monkeypatch, admin_headers):
        """Test that when no secret is set, any header value works."""
        # Directly patch the os.getenv call in the module to return None
        with patch('a2a_server.routes.session_export.os.getenv', return_value=None):
            response = client.get("/sessions", headers=admin_headers)
            assert response.status_code == 200


class TestListSessions:
    """Test the list sessions endpoint."""
    
    def test_list_sessions_default_handler(self, client, admin_headers):
        """Test listing sessions using default handler."""
        response = client.get("/sessions", headers=admin_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["handler"] == "session_handler"
        assert "sessions" in data
        assert len(data["sessions"]) == 2
        assert "session1" in data["sessions"]
        assert "session2" in data["sessions"]
    
    def test_list_sessions_specific_handler(self, client, admin_headers):
        """Test listing sessions using specific handler."""
        response = client.get("/sessions?handler_name=session_handler", headers=admin_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["handler"] == "session_handler"
    
    def test_list_sessions_with_details(self, client, admin_headers):
        """Test listing sessions with detailed information."""
        response = client.get("/sessions?with_details=true", headers=admin_headers)
        assert response.status_code == 200
        
        data = response.json()
        sessions = data["sessions"]
        assert len(sessions) == 2
        assert isinstance(sessions[0], dict)
        assert "id" in sessions[0]
        assert "created" in sessions[0]
        assert "messages" in sessions[0]
    
    def test_list_sessions_handler_not_found(self, client, admin_headers):
        """Test listing sessions with non-existent handler."""
        response = client.get("/sessions?handler_name=nonexistent", headers=admin_headers)
        assert response.status_code == 404
        assert "Handler nonexistent not found" in response.json()["detail"]
    
    def test_list_sessions_handler_lacks_capability(self, client, admin_headers):
        """Test listing sessions with handler that doesn't support it."""
        response = client.get("/sessions?handler_name=insufficient_handler", headers=admin_headers)
        assert response.status_code == 400
        assert "does not support 'list_sessions'" in response.json()["detail"]


class TestExportSession:
    """Test the export session endpoint."""
    
    def test_export_session_success(self, client, admin_headers):
        """Test successful session export."""
        response = client.get("/sessions/session1/export", headers=admin_headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert "attachment" in response.headers["content-disposition"]
        assert "session_session1_session_handler.json" in response.headers["content-disposition"]
        
        data = json.loads(response.content)
        assert data["session_id"] == "session1"
        assert data["handler"] == "session_handler"
        assert len(data["conversation"]) == 4
        assert "exported_at" in data
        assert "token_usage" in data
        assert data["token_usage"]["total_tokens"] == 150
    
    def test_export_session_without_token_usage(self, client, admin_headers):
        """Test session export without token usage."""
        response = client.get(
            "/sessions/session1/export?include_token_usage=false", 
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = json.loads(response.content)
        assert "token_usage" not in data
    
    def test_export_session_not_found(self, client, admin_headers):
        """Test exporting non-existent session."""
        response = client.get("/sessions/nonexistent/export", headers=admin_headers)
        assert response.status_code == 200  # Handler returns empty conversation
        
        data = json.loads(response.content)
        assert data["session_id"] == "nonexistent"
        assert len(data["conversation"]) == 0
    
    def test_export_session_specific_handler(self, client, admin_headers):
        """Test exporting session with specific handler."""
        response = client.get(
            "/sessions/session1/export?handler_name=session_handler", 
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = json.loads(response.content)
        assert data["handler"] == "session_handler"


class TestImportSession:
    """Test the import session endpoint."""
    
    def test_import_session_success(self, client, admin_headers):
        """Test successful session import."""
        session_data = {
            "conversation": [
                {"role": "user", "content": "Hello, imported message"},
                {"role": "assistant", "content": "Hi! This is imported too."}
            ]
        }
        
        response = client.post("/sessions/import", headers=admin_headers, json=session_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "new_session_id" in data
        assert data["handler"] == "session_handler"
        assert data["imported_messages"] == 2
    
    def test_import_session_empty_conversation(self, client, admin_headers):
        """Test importing session with empty conversation."""
        session_data = {"conversation": []}
        
        response = client.post("/sessions/import", headers=admin_headers, json=session_data)
        assert response.status_code == 400
        assert "No messages imported" in response.json()["detail"]
    
    def test_import_session_missing_conversation(self, client, admin_headers):
        """Test importing session without conversation field."""
        session_data = {"some_other_field": "value"}
        
        response = client.post("/sessions/import", headers=admin_headers, json=session_data)
        assert response.status_code == 400
        assert "missing 'conversation' list" in response.json()["detail"]
    
    def test_import_session_with_handler_name(self, client, admin_headers):
        """Test importing session with specific handler."""
        session_data = {
            "conversation": [
                {"role": "user", "content": "Test message"}
            ]
        }
        
        response = client.post(
            "/sessions/import?handler_name=session_handler", 
            headers=admin_headers, 
            json=session_data
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["handler"] == "session_handler"
    
    def test_import_session_handler_from_data(self, client, admin_headers):
        """Test importing session with handler specified in data."""
        session_data = {
            "handler": "session_handler",
            "conversation": [
                {"role": "user", "content": "Test message"}
            ]
        }
        
        response = client.post("/sessions/import", headers=admin_headers, json=session_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["handler"] == "session_handler"


class TestDeleteSession:
    """Test the delete session endpoint."""
    
    def test_delete_session_success(self, client, admin_headers):
        """Test successful session deletion."""
        response = client.delete("/sessions/session1", headers=admin_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert data["session_id"] == "session1"
    
    def test_delete_session_not_found(self, client, admin_headers):
        """Test deleting non-existent session."""
        response = client.delete("/sessions/nonexistent", headers=admin_headers)
        assert response.status_code == 404
        assert "Session not found or already deleted" in response.json()["detail"]
    
    def test_delete_session_specific_handler(self, client, admin_headers):
        """Test deleting session with specific handler."""
        response = client.delete(
            "/sessions/session1?handler_name=session_handler", 
            headers=admin_headers
        )
        assert response.status_code == 200
    
    def test_delete_session_handler_lacks_capability(self, client, admin_headers):
        """Test deleting session with handler that doesn't support it."""
        response = client.delete(
            "/sessions/session1?handler_name=insufficient_handler", 
            headers=admin_headers
        )
        assert response.status_code == 400
        assert "does not support 'delete_session'" in response.json()["detail"]


class TestCapabilityChecking:
    """Test capability checking for different operations."""
    
    def test_get_conversation_history_capability(self, client, admin_headers):
        """Test that get_conversation_history capability is checked."""
        response = client.get(
            "/sessions/session1/export?handler_name=insufficient_handler", 
            headers=admin_headers
        )
        assert response.status_code == 400
        assert "does not support 'session export'" in response.json()["detail"]
    
    def test_add_to_session_capability(self, client, admin_headers):
        """Test that add_to_session capability is checked."""
        session_data = {
            "conversation": [{"role": "user", "content": "Test"}]
        }
        
        response = client.post(
            "/sessions/import?handler_name=insufficient_handler", 
            headers=admin_headers, 
            json=session_data
        )
        assert response.status_code == 400
        assert "does not support 'session import'" in response.json()["detail"]


class TestErrorHandling:
    """Test error handling in session routes."""
    
    def test_handler_exception_in_export(self, client, admin_headers):
        """Test handling of exceptions during export."""
        with patch.object(MockHandler, 'get_conversation_history', side_effect=Exception("Test error")):
            response = client.get("/sessions/session1/export", headers=admin_headers)
            assert response.status_code == 500
            assert "Test error" in response.json()["detail"]
    
    def test_handler_exception_in_delete(self, client, admin_headers):
        """Test handling of exceptions during delete."""
        with patch.object(MockHandler, 'delete_session', side_effect=Exception("Delete error")):
            response = client.delete("/sessions/session1", headers=admin_headers)
            assert response.status_code == 500
            assert "Delete error" in response.json()["detail"]


class TestBackwardsCompatibility:
    """Test backwards compatibility aliases."""
    
    def test_register_session_export_routes_alias(self):
        """Test that the old function name still works."""
        from a2a_server.routes.session_export import register_session_export_routes
        
        app = FastAPI()
        # Set up minimal state first
        app.state.task_manager = MockTaskManager()
        
        # Should not raise an error
        register_session_export_routes(app)
        
        # Should have registered the same routes
        client = TestClient(app)
        admin_headers = {"X-Internal-Admin": "test"}
        
        response = client.get("/sessions", headers=admin_headers)
        assert response.status_code == 200  # Should work now with proper state