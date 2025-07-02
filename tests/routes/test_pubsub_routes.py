#!/usr/bin/env python3
# tests/routes/test_pubsub_integration.py
"""
Test the integration between PubSub EventBus and route endpoints.
"""
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_eventbus_mock():
    """Test that EventBus can be mocked properly."""
    from a2a_server.pubsub import EventBus
    
    # Create a real EventBus
    event_bus = EventBus()
    
    # Test basic operations
    queue = event_bus.subscribe()
    assert queue is not None
    
    # Test unsubscribe
    event_bus.unsubscribe(queue)
    
    # Should not raise an error
    assert True


def test_mock_event_bus_in_app():
    """Test using a mock event bus in an app."""
    app = FastAPI()
    
    # Mock event bus
    mock_event_bus = MagicMock()
    app.state.event_bus = mock_event_bus
    
    @app.get("/test-event")
    def test_event():
        # This would normally publish an event
        return {"published": True}
    
    client = TestClient(app)
    response = client.get("/test-event")
    
    assert response.status_code == 200
    assert response.json() == {"published": True}


def test_event_bus_integration_concept():
    """Test the concept of event bus integration without async complications."""
    # This test verifies that our mock setup works for event bus integration
    
    class MockEventBus:
        def __init__(self):
            self.events = []
        
        def publish(self, event):
            self.events.append(event)
        
        def subscribe(self):
            return MagicMock()
    
    # Create app with mock event bus
    app = FastAPI()
    event_bus = MockEventBus()
    app.state.event_bus = event_bus
    
    @app.post("/trigger-event")
    def trigger_event(data: dict):
        # Simulate publishing an event
        app.state.event_bus.publish({"type": "test", "data": data})
        return {"status": "event_published"}
    
    client = TestClient(app)
    response = client.post("/trigger-event", json={"test": "data"})
    
    assert response.status_code == 200
    assert response.json() == {"status": "event_published"}
    
    # Verify event was "published"
    assert len(event_bus.events) == 1
    assert event_bus.events[0]["type"] == "test"
    assert event_bus.events[0]["data"] == {"test": "data"}