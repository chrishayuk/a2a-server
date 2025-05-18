# tests/routes/test_handler_routes.py
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a2a_server.routes.handlers import register_handler_routes


class MockTaskManager:
    """Mock TaskManager for testing."""
    
    def get_handlers(self):
        return {"echo": "echo", "pirate_agent": "pirate_agent", "chef_agent": "chef_agent"}
        
    def get_default_handler(self):
        return "echo"


class MockEventBus:
    """Mock EventBus for testing."""
    
    async def publish(self, event):
        pass


@pytest.fixture
def app():
    """Create a test FastAPI app with handler routes registered."""
    app = FastAPI()
    
    # Configure mock task manager
    task_manager = MockTaskManager()
    
    # Mock handlers_config
    handlers_config = {
        "echo": {
            "type": "EchoHandler",
            "agent_card": {
                "name": "Echo Handler",
                "description": "Simple echo handler for testing",
            }
        },
        "pirate_agent": {
            "type": "GoogleADKHandler",
            "agent_card": {
                "name": "Pirate Agent",
                "description": "Talks like a pirate",
            }
        },
        "chef_agent": {
            "type": "GoogleADKHandler",
            "agent_card": {
                "name": "Chef Agent",
                "description": "Provides cooking tips and recipes",
            }
        }
    }
    
    # Register handler routes
    register_handler_routes(app, task_manager, handlers_config)
    
    # Set up app state
    app.state.event_bus = MockEventBus()
    
    return app


@pytest.fixture
def client(app):
    """Create a TestClient for the app."""
    return TestClient(app)


def test_handler_health_endpoints(client):
    """Test the handler health endpoints for all mock handlers."""
    for handler in ["echo", "pirate_agent", "chef_agent"]:
        response = client.get(f"/{handler}")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify structure
        assert "handler" in data
        assert data["handler"] == handler
        
        assert "endpoints" in data
        assert "rpc" in data["endpoints"]
        assert "events" in data["endpoints"]
        assert "ws" in data["endpoints"]
        
        assert data["endpoints"]["rpc"] == f"/{handler}/rpc"
        assert data["endpoints"]["events"] == f"/{handler}/events"
        assert data["endpoints"]["ws"] == f"/{handler}/ws"
        
        assert "handler_agent_card" in data
        assert data["handler_agent_card"].endswith(f"/{handler}/.well-known/agent.json")


@patch("a2a_server.agent_card.get_agent_cards")
def test_handler_agent_cards(mock_get_agent_cards, client, app):
    """Test the handler-specific agent card endpoints."""
    # Set up test cards for each handler
    mock_cards = {
        "echo": MagicMock(dict=lambda exclude_none: {
            "name": "Echo Handler",
            "description": "Simple echo handler for testing",
            "url": "http://testserver/echo"
        }),
        "pirate_agent": MagicMock(dict=lambda exclude_none: {
            "name": "Pirate Agent",
            "description": "Talks like a pirate",
            "url": "http://testserver/pirate_agent"
        }),
        "chef_agent": MagicMock(dict=lambda exclude_none: {
            "name": "Chef Agent",
            "description": "Provides cooking tips and recipes",
            "url": "http://testserver/chef_agent"
        })
    }
    
    # Setup the mock to return our test cards
    mock_get_agent_cards.return_value = mock_cards
    
    # Test each handler's agent card endpoint
    for handler in ["echo", "pirate_agent", "chef_agent"]:
        response = client.get(f"/{handler}/.well-known/agent.json")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify the agent card data
        if handler == "echo":
            assert data["name"] == "Echo Handler"
            assert data["description"] == "Simple echo handler for testing"
        elif handler == "pirate_agent":
            assert data["name"] == "Pirate Agent"
            assert data["description"] == "Talks like a pirate"
        elif handler == "chef_agent":
            assert data["name"] == "Chef Agent"
            assert data["description"] == "Provides cooking tips and recipes"
        
        assert data["url"] == f"http://testserver/{handler}"


@patch("a2a_server.agent_card.get_agent_cards")
def test_handler_agent_card_fallback(mock_get_agent_cards, client, app):
    """Test the fallback behavior when a handler's agent card is not found."""
    # Setup the mock to return an empty dictionary (no cards)
    mock_get_agent_cards.return_value = {}
    
    response = client.get("/echo/.well-known/agent.json")
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify fallback card generation
    assert data["name"] == "Echo Handler"  # Using the handler's agent card name from config
    assert "description" in data
    
    # Verify the correct field name formatting (camelCase vs snake_case)
    # Pydantic v2 models typically output camelCase by default with json serialization
    assert "defaultInputModes" in data or "default_input_modes" in data
    assert "capabilities" in data
    if "capabilities" in data:
        assert "streaming" in data["capabilities"]
    
    # Check the URL which should still be handler-specific
    assert "url" in data
    assert data["url"].endswith("/echo")
    assert "version" in data
    assert "skills" in data
    assert len(data["skills"]) == 1
    assert data["skills"][0]["id"] == "echo-default"

@patch("a2a_server.agent_card.get_agent_cards")
def test_handler_sse_streaming(mock_get_agent_cards, monkeypatch, client, app):
    """Test that handler endpoint handles SSE streaming with task_ids."""
    # Mock the _create_sse_response function
    called_with_task_ids = []
    
    async def mock_create_sse_response(event_bus, task_ids):
        called_with_task_ids.append(task_ids)
        # Return a dict response instead of streaming response for testing
        return {"streaming": True, "task_ids": task_ids}
    
    # Apply the mock
    monkeypatch.setattr("a2a_server.routes.handlers._create_sse_response", mock_create_sse_response)
    
    # Test with task_ids parameter
    response = client.get("/echo?task_ids=task1,task2")
    assert response.status_code == 200
    
    # Verify the mock was called with the right task_ids
    assert len(called_with_task_ids) == 1
    # In your implementation, task_ids is passed as a single string, not split into a list
    assert called_with_task_ids[0] == ["task1,task2"]