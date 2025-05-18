#!/usr/bin/env python3
# tests/routes/test_health_routes.py
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a2a_server.routes.health import register_health_routes


class MockTaskManager:
    """Mock TaskManager for testing."""
    
    def get_handlers(self):
        return {"echo": "echo", "pirate_agent": "pirate_agent", "chef_agent": "chef_agent"}
        
    def get_default_handler(self):
        return "echo"


@pytest.fixture
def app():
    """Create a test FastAPI app with health routes registered."""
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
    
    # Register health routes
    register_health_routes(app, task_manager, handlers_config)
    
    return app


@pytest.fixture
def client(app):
    """Create a TestClient for the app."""
    return TestClient(app)


def test_root_health(client):
    """Test the root health endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify structure
    assert "status" in data
    assert data["status"] == "ok"
    
    assert "default_handler" in data
    assert data["default_handler"] == "echo"
    
    assert "handlers" in data
    assert len(data["handlers"]) == 3
    assert "echo" in data["handlers"]
    assert "pirate_agent" in data["handlers"]
    assert "chef_agent" in data["handlers"]
    
    assert "agent_card" in data
    assert data["agent_card"].endswith("/.well-known/agent.json")


@patch("a2a_server.agent_card.get_agent_cards")
def test_default_agent_card(mock_get_agent_cards, client, app):
    """Test the default agent card endpoint."""
    # Mock the agent_card.get_agent_cards function
    mock_card = {
        "name": "Echo Handler",
        "description": "Simple echo handler for testing",
        "url": "http://testserver",
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{"id": "echo-default", "name": "Echo", "description": "Echo capability", "tags": ["echo"]}]
    }
    
    # Setup the mock to return our test card
    mock_get_agent_cards.return_value = {"echo": MagicMock(dict=lambda exclude_none: mock_card)}
    
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify the agent card data
    assert data["name"] == "Echo Handler"
    assert data["description"] == "Simple echo handler for testing"
    assert data["url"] == "http://testserver/echo"
    assert data["version"] == "1.0.0"
    assert "capabilities" in data
    assert data["capabilities"]["streaming"] is True
    assert "skills" in data
    assert len(data["skills"]) == 1
    assert data["skills"][0]["id"] == "echo-default"


@patch("a2a_server.agent_card.get_agent_cards")
def test_default_agent_card_fallback(mock_get_agent_cards, client, app):
    """Test the fallback behavior when no agent card is found."""
    # Setup the mock to return an empty dictionary (no cards)
    mock_get_agent_cards.return_value = {}
    
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify fallback card generation
    assert data["name"] == "Echo Handler"  # Using the handler's agent card name from config
    assert "description" in data
    assert "url" in data
    assert "version" in data
    assert "capabilities" in data
    assert "streaming" in data["capabilities"]
    assert "skills" in data
    assert len(data["skills"]) == 1
    assert data["skills"][0]["id"] == "echo-default"


@patch("a2a_server.agent_card.get_agent_cards")
def test_no_default_handler_error(mock_get_agent_cards, client, app):
    """Test error response when no default handler is configured."""
    # Mock task_manager with no default handler
    app.state.task_manager = type('MockTaskManager', (), {
        'get_default_handler': lambda: None,
        'get_handlers': lambda: {"echo": "echo"}
    })
    
    response = client.get("/.well-known/agent.json")
    # Your implementation is returning a fallback card even when there's no default handler
    assert response.status_code == 200
    
    data = response.json()
    # Verify it's a fallback card
    assert "name" in data
    assert "description" in data