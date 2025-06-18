# tests/server/test_task_handler_registry.py
import pytest
from a2a_server.tasks.handlers.task_handler_registry import TaskHandlerRegistry
from a2a_server.tasks.handlers.task_handler import TaskHandler

# Create some test handlers
class TestHandler1(TaskHandler):
    @property
    def name(self) -> str:
        return "handler1"
    
    async def process_task(self, task_id, message, session_id=None):
        yield "test1"

class TestHandler2(TaskHandler):
    @property
    def name(self) -> str:
        return "handler2"
    
    async def process_task(self, task_id, message, session_id=None):
        yield "test2"

class TestHandler3(TaskHandler):
    @property
    def name(self) -> str:
        return "handler3"
    
    async def process_task(self, task_id, message, session_id=None):
        yield "test3"

@pytest.fixture
def registry():
    """Create a fresh registry for each test."""
    return TaskHandlerRegistry()

def test_empty_registry(registry):
    """Test that a new registry has no handlers."""
    assert registry._handlers == {}
    assert registry._default_handler is None
    assert registry.get_all() == {}

def test_register_handler(registry):
    """Test registering a handler."""
    handler = TestHandler1()
    registry.register(handler)
    
    # Check internal state
    assert registry._handlers == {"handler1": handler}
    assert registry.get_all() == {"handler1": handler}
    
    # First handler should be default
    assert registry._default_handler == "handler1"
    
def test_register_multiple_handlers(registry):
    """Test registering multiple handlers."""
    handler1 = TestHandler1()
    handler2 = TestHandler2()
    handler3 = TestHandler3()
    
    registry.register(handler1)
    registry.register(handler2)
    registry.register(handler3)
    
    # Check all handlers are registered
    assert registry._handlers == {
        "handler1": handler1,
        "handler2": handler2,
        "handler3": handler3
    }
    
    # First registered should be default
    assert registry._default_handler == "handler1"
    
def test_register_with_default(registry):
    """Test registering a handler as default."""
    handler1 = TestHandler1()
    handler2 = TestHandler2()
    
    # Register without default flag
    registry.register(handler1)
    # Register with default flag
    registry.register(handler2, default=True)
    
    # Second handler should be default
    assert registry._default_handler == "handler2"

def test_get_handler_by_name(registry):
    """Test getting a handler by name."""
    handler1 = TestHandler1()
    handler2 = TestHandler2()
    
    registry.register(handler1)
    registry.register(handler2)
    
    # Get by name
    assert registry.get("handler1") is handler1
    assert registry.get("handler2") is handler2

def test_get_default_handler(registry):
    """Test getting the default handler."""
    handler1 = TestHandler1()
    handler2 = TestHandler2()
    
    registry.register(handler1)
    registry.register(handler2, default=True)
    
    # Get default
    assert registry.get() is handler2

def test_get_nonexistent_handler(registry):
    """Test getting a handler that doesn't exist."""
    with pytest.raises(KeyError):
        registry.get("nonexistent")

def test_get_default_when_none_set(registry):
    """Test getting the default handler when none is set."""
    with pytest.raises(ValueError, match="No default handler registered"):
        registry.get()

def test_replace_handler(registry):
    """Test that registering with the same name replaces the handler."""
    handler1a = TestHandler1()
    handler1b = TestHandler1()  # Same name but different instance
    
    registry.register(handler1a)
    assert registry.get("handler1") is handler1a
    
    # Register again with same name
    registry.register(handler1b)
    assert registry.get("handler1") is handler1b

def test_get_all_returns_copy(registry):
    """Test that get_all returns a copy, not the original dict."""
    handler1 = TestHandler1()
    registry.register(handler1)
    
    # Get all handlers
    all_handlers = registry.get_all()
    assert all_handlers == {"handler1": handler1}
    
    # Modify the returned dict
    all_handlers["new"] = "value"
    
    # Original should be unchanged
    assert registry._handlers == {"handler1": handler1}
    assert "new" not in registry._handlers