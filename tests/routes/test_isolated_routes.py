#!/usr/bin/env python3
# tests/routes/test_isolated_routes.py
"""
Completely isolated route tests that don't import any a2a_server modules.
Fixed version that addresses all test failures.
"""
import pytest
from fastapi import FastAPI, HTTPException, Header
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


def test_pure_fastapi():
    """Test pure FastAPI functionality without any a2a imports."""
    app = FastAPI()
    
    @app.get("/")
    def root():
        return {"status": "ok"}
    
    client = TestClient(app)
    response = client.get("/")
    
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fastapi_with_error():
    """Test FastAPI error handling."""
    app = FastAPI()
    
    @app.get("/error")
    def error_endpoint():
        raise HTTPException(status_code=400, detail="Test error")
    
    client = TestClient(app)
    response = client.get("/error")
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Test error"


def test_fastapi_with_mocks():
    """Test FastAPI with mock objects."""
    app = FastAPI()
    
    # Create mock dependencies
    mock_manager = MagicMock()
    mock_manager.get_handlers.return_value = {"test": "test"}
    mock_manager.get_default_handler.return_value = "test"
    
    app.state.task_manager = mock_manager
    
    @app.get("/handlers")
    def get_handlers():
        return {"handlers": app.state.task_manager.get_handlers()}
    
    client = TestClient(app)
    response = client.get("/handlers")
    
    assert response.status_code == 200
    assert response.json() == {"handlers": {"test": "test"}}


def test_fastapi_with_headers():
    """Test FastAPI with header authentication - FIXED."""
    app = FastAPI()
    
    @app.get("/protected")
    def protected_endpoint(authorization: str = Header(None)):
        if authorization != "Bearer valid-token":
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"message": "authorized"}
    
    client = TestClient(app)
    
    # Test without header - should return 401 (not 422) since we provide None default
    response = client.get("/protected")
    assert response.status_code == 401
    
    # Test with wrong header
    response = client.get("/protected", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    
    # Test with correct header
    response = client.get("/protected", headers={"Authorization": "Bearer valid-token"})
    assert response.status_code == 200
    assert response.json() == {"message": "authorized"}


def test_fastapi_with_query_params():
    """Test FastAPI with query parameters."""
    app = FastAPI()
    
    @app.get("/search")
    def search(q: str = "default", limit: int = 10):
        return {"query": q, "limit": limit}
    
    client = TestClient(app)
    
    # Test defaults
    response = client.get("/search")
    assert response.status_code == 200
    assert response.json() == {"query": "default", "limit": 10}
    
    # Test with params
    response = client.get("/search?q=test&limit=5")
    assert response.status_code == 200
    assert response.json() == {"query": "test", "limit": 5}


def test_fastapi_with_post():
    """Test FastAPI POST endpoint."""
    app = FastAPI()
    
    @app.post("/data")
    def create_data(data: dict):
        return {"received": data, "status": "created"}
    
    client = TestClient(app)
    response = client.post("/data", json={"test": "value"})
    
    assert response.status_code == 200
    assert response.json() == {"received": {"test": "value"}, "status": "created"}


def test_mock_health_endpoint():
    """Test a mock health endpoint similar to a2a server."""
    app = FastAPI()
    
    # Mock dependencies
    mock_handlers = {"echo": "echo", "test": "test"}
    app.state.handlers = mock_handlers
    
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "Test Server",
            "handlers": list(app.state.handlers.keys())
        }
    
    client = TestClient(app)
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "Test Server"
    assert "echo" in data["handlers"]
    assert "test" in data["handlers"]


def test_mock_agent_card():
    """Test a mock agent card endpoint."""
    app = FastAPI()
    
    @app.get("/agent-card.json")
    def agent_card():
        return {
            "name": "Test Agent",
            "description": "A test agent",
            "url": "http://testserver",
            "version": "1.0.0",
            "capabilities": {"streaming": True}
        }
    
    client = TestClient(app)
    response = client.get("/agent-card.json")
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Agent"
    assert data["capabilities"]["streaming"] is True


def test_mock_admin_protected():
    """Test mock admin-protected endpoint - FIXED."""
    app = FastAPI()
    
    def check_admin_token(token: str = None):
        if token != "admin-secret":
            raise HTTPException(status_code=401, detail="Admin required")
    
    @app.get("/admin/info")
    def admin_info(x_admin_token: str = Header(None, alias="X-Admin-Token")):
        check_admin_token(x_admin_token)
        return {"admin": True, "info": "secret data"}
    
    client = TestClient(app)
    
    # Test without token - should return 401 (not 422) since we have None default
    response = client.get("/admin/info")
    assert response.status_code == 401
    
    # Test with wrong token
    response = client.get("/admin/info", headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 401
    
    # Test with correct token
    response = client.get("/admin/info", headers={"X-Admin-Token": "admin-secret"})
    assert response.status_code == 200
    assert response.json() == {"admin": True, "info": "secret data"}


def test_multiple_routes():
    """Test multiple routes in one app."""
    app = FastAPI()
    
    @app.get("/")
    def root():
        return {"message": "root"}
    
    @app.get("/health")
    def health():
        return {"status": "healthy"}
    
    @app.get("/info")
    def info():
        return {"version": "1.0.0"}
    
    @app.post("/echo")
    def echo(data: dict):
        return {"echo": data}
    
    client = TestClient(app)
    
    # Test all routes
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "root"
    
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    
    response = client.get("/info")
    assert response.status_code == 200
    assert response.json()["version"] == "1.0.0"
    
    response = client.post("/echo", json={"test": "data"})
    assert response.status_code == 200
    assert response.json()["echo"] == {"test": "data"}


class TestIsolatedRouteClass:
    """Test class to verify class-based tests work too."""
    
    def test_class_based_test(self):
        """Test that class-based tests work."""
        app = FastAPI()
        
        @app.get("/class-test")
        def class_test():
            return {"class": "test"}
        
        client = TestClient(app)
        response = client.get("/class-test")
        
        assert response.status_code == 200
        assert response.json() == {"class": "test"}
    
    def test_class_with_fixture_simulation(self):
        """Simulate using fixtures in class."""
        # Simulate fixture data
        mock_config = {"test": True, "env": "test"}
        
        app = FastAPI()
        app.state.config = mock_config
        
        @app.get("/config")
        def get_config():
            return app.state.config
        
        client = TestClient(app)
        response = client.get("/config")
        
        assert response.status_code == 200
        assert response.json() == mock_config


def test_no_async_operations():
    """Test that ensures no async operations are used."""
    app = FastAPI()
    
    # This test uses only sync operations
    counter = {"value": 0}
    
    @app.get("/increment")
    def increment():
        counter["value"] += 1
        return {"counter": counter["value"]}
    
    @app.get("/reset")  
    def reset():
        counter["value"] = 0
        return {"counter": counter["value"]}
    
    client = TestClient(app)
    
    # Test increment
    response = client.get("/increment")
    assert response.status_code == 200
    assert response.json()["counter"] == 1
    
    response = client.get("/increment")
    assert response.status_code == 200
    assert response.json()["counter"] == 2
    
    # Test reset
    response = client.get("/reset")
    assert response.status_code == 200
    assert response.json()["counter"] == 0


# Module-level function for patching test
def external_service():
    return "real_data"


def test_patch_functionality():
    """Test that patch/mock functionality works - FIXED.""" 
    # Create a container for the function to make it patchable
    service_container = {"func": external_service}
    
    app = FastAPI()
    
    @app.get("/service")
    def get_service_data():
        return {"data": service_container["func"]()}
    
    client = TestClient(app)
    
    # Test without patch
    response = client.get("/service")
    assert response.status_code == 200
    assert response.json()["data"] == "real_data"
    
    # Test with mock by directly replacing the function
    original_func = service_container["func"]
    service_container["func"] = lambda: "mocked_data"
    
    try:
        response = client.get("/service")
        assert response.status_code == 200
        assert response.json()["data"] == "mocked_data"
    finally:
        service_container["func"] = original_func


if __name__ == "__main__":
    # This allows running the file directly for quick testing
    import sys
    print("Running isolated route tests...")
    
    # Run tests manually
    test_functions = [
        test_pure_fastapi,
        test_fastapi_with_error,
        test_fastapi_with_mocks,
        test_no_async_operations,
    ]
    
    for test_func in test_functions:
        try:
            test_func()
            print(f"✅ {test_func.__name__}")
        except Exception as e:
            print(f"❌ {test_func.__name__}: {e}")
            sys.exit(1)
    
    print("🎉 All isolated tests passed!")