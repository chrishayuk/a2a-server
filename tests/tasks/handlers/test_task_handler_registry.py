# tests/tasks/test_task_handler_registry.py
"""
Tests for TaskHandlerRegistry
==============================
Tests the task handler registry that manages handler registration and selection.
"""

import pytest
from a2a_server.tasks.task_handler_registry import TaskHandlerRegistry
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


@pytest.fixture
def sample_handlers():
    """Create sample handlers for testing."""
    return {
        "handler1": TestHandler1(),
        "handler2": TestHandler2(),
        "handler3": TestHandler3()
    }


class TestTaskHandlerRegistry:
    """Test suite for TaskHandlerRegistry."""

    def test_empty_registry(self, registry):
        """Test that a new registry has no handlers."""
        assert registry._handlers == {}
        assert registry._default_handler is None
        assert registry.get_all() == {}

    def test_register_handler(self, registry):
        """Test registering a handler."""
        handler = TestHandler1()
        registry.register(handler)
        
        # Check internal state
        assert registry._handlers == {"handler1": handler}
        assert registry.get_all() == {"handler1": handler}
        
        # First handler should be default
        assert registry._default_handler == "handler1"

    def test_register_multiple_handlers(self, registry, sample_handlers):
        """Test registering multiple handlers."""
        handler1 = sample_handlers["handler1"]
        handler2 = sample_handlers["handler2"]
        handler3 = sample_handlers["handler3"]
        
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

    def test_register_with_default(self, registry, sample_handlers):
        """Test registering a handler as default."""
        handler1 = sample_handlers["handler1"]
        handler2 = sample_handlers["handler2"]
        
        # Register without default flag
        registry.register(handler1)
        # Register with default flag
        registry.register(handler2, default=True)
        
        # Second handler should be default
        assert registry._default_handler == "handler2"

    def test_get_handler_by_name(self, registry, sample_handlers):
        """Test getting a handler by name."""
        handler1 = sample_handlers["handler1"]
        handler2 = sample_handlers["handler2"]
        
        registry.register(handler1)
        registry.register(handler2)
        
        # Get by name
        assert registry.get("handler1") is handler1
        assert registry.get("handler2") is handler2

    def test_get_default_handler(self, registry, sample_handlers):
        """Test getting the default handler."""
        handler1 = sample_handlers["handler1"]
        handler2 = sample_handlers["handler2"]
        
        registry.register(handler1)
        registry.register(handler2, default=True)
        
        # Get default
        assert registry.get() is handler2

    def test_get_nonexistent_handler(self, registry):
        """Test getting a handler that doesn't exist."""
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_get_default_when_none_set(self, registry):
        """Test getting the default handler when none is set."""
        with pytest.raises(ValueError, match="No default handler registered"):
            registry.get()

    def test_replace_handler(self, registry):
        """Test that registering with the same name replaces the handler."""
        handler1a = TestHandler1()
        handler1b = TestHandler1()  # Same name but different instance
        
        registry.register(handler1a)
        assert registry.get("handler1") is handler1a
        
        # Register again with same name
        registry.register(handler1b)
        assert registry.get("handler1") is handler1b

    def test_get_all_returns_copy(self, registry, sample_handlers):
        """Test that get_all returns a copy, not the original dict."""
        handler1 = sample_handlers["handler1"]
        registry.register(handler1)
        
        # Get all handlers
        all_handlers = registry.get_all()
        assert all_handlers == {"handler1": handler1}
        
        # Modify the returned dict
        all_handlers["new"] = "value"
        
        # Original should be unchanged
        assert registry._handlers == {"handler1": handler1}
        assert "new" not in registry._handlers

    def test_register_multiple_with_explicit_defaults(self, registry, sample_handlers):
        """Test registering multiple handlers with explicit default settings."""
        handler1 = sample_handlers["handler1"]
        handler2 = sample_handlers["handler2"]
        handler3 = sample_handlers["handler3"]
        
        # Register first handler (should become default)
        registry.register(handler1)
        assert registry._default_handler == "handler1"
        
        # Register second without default flag (should not change default)
        registry.register(handler2, default=False)
        assert registry._default_handler == "handler1"
        
        # Register third with default=True (should become new default)
        registry.register(handler3, default=True)
        assert registry._default_handler == "handler3"

    def test_handler_name_consistency(self, registry):
        """Test that handler names must be consistent with their name property."""
        class InconsistentHandler(TaskHandler):
            def __init__(self, reported_name):
                self._reported_name = reported_name
                
            @property
            def name(self) -> str:
                return self._reported_name
                
            async def process_task(self, task_id, message, session_id=None):
                yield "inconsistent"
        
        handler = InconsistentHandler("custom_name")
        registry.register(handler)
        
        # Should be registered under its actual name property
        assert "custom_name" in registry.get_all()
        assert registry.get("custom_name") is handler

    def test_default_handler_behavior_edge_cases(self, registry, sample_handlers):
        """Test edge cases in default handler behavior."""
        handler1 = sample_handlers["handler1"]
        handler2 = sample_handlers["handler2"]
        
        # Register first handler with explicit default=False
        registry.register(handler1, default=False)
        
        # Should still become default since it's the first
        assert registry._default_handler == "handler1"
        
        # Register second with default=False 
        registry.register(handler2, default=False)
        
        # Default should remain unchanged
        assert registry._default_handler == "handler1"

    def test_registry_state_isolation(self):
        """Test that multiple registries don't interfere with each other."""
        registry1 = TaskHandlerRegistry()
        registry2 = TaskHandlerRegistry()
        
        handler1 = TestHandler1()
        handler2 = TestHandler2()
        
        registry1.register(handler1)
        registry2.register(handler2)
        
        # Each registry should have only its own handlers
        assert list(registry1.get_all().keys()) == ["handler1"]
        assert list(registry2.get_all().keys()) == ["handler2"]
        
        assert registry1.get() is handler1
        assert registry2.get() is handler2

    def test_handler_registration_order(self, registry, sample_handlers):
        """Test that registration order is preserved in get_all()."""
        handlers = [
            sample_handlers["handler3"],
            sample_handlers["handler1"], 
            sample_handlers["handler2"]
        ]
        
        for handler in handlers:
            registry.register(handler)
        
        all_handlers = registry.get_all()
        
        # Python 3.7+ dicts preserve insertion order
        assert list(all_handlers.keys()) == ["handler3", "handler1", "handler2"]

    def test_registry_with_real_handlers(self, registry):
        """Test registry with actual handler implementations."""
        try:
            from a2a_server.tasks.handlers.echo_handler import EchoHandler
            
            echo_handler = EchoHandler()
            test_handler = TestHandler1()
            
            registry.register(echo_handler)
            registry.register(test_handler, default=True)
            
            # Should be able to retrieve both
            assert registry.get("echo") is echo_handler
            assert registry.get("handler1") is test_handler
            assert registry.get() is test_handler  # default
            
            all_handlers = registry.get_all()
            assert len(all_handlers) == 2
            assert "echo" in all_handlers
            assert "handler1" in all_handlers
            
        except ImportError:
            pytest.skip("Echo handler not available")


class TestRegistryErrorHandling:
    """Test error handling in TaskHandlerRegistry."""

    def test_none_handler_registration(self, registry):
        """Test that registering None raises appropriate error."""
        with pytest.raises(AttributeError):
            registry.register(None)

    def test_invalid_handler_type(self, registry):
        """Test registering object that's not a TaskHandler."""
        class NotAHandler:
            @property
            def name(self):
                return "fake"
        
        fake_handler = NotAHandler()
        
        # Should register but may cause issues when used
        # The registry doesn't validate handler types at registration
        registry.register(fake_handler)
        assert registry.get("fake") is fake_handler

    def test_handler_without_name_property(self, registry):
        """Test handler without name property."""
        class NamelessHandler:
            async def process_task(self, task_id, message, session_id=None):
                yield "nameless"
        
        nameless = NamelessHandler()
        
        with pytest.raises(AttributeError):
            registry.register(nameless)

    def test_empty_handler_name(self, registry):
        """Test handler with empty name."""
        class EmptyNameHandler(TaskHandler):
            @property
            def name(self) -> str:
                return ""
                
            async def process_task(self, task_id, message, session_id=None):
                yield "empty"
        
        handler = EmptyNameHandler()
        registry.register(handler)
        
        # Should register with empty string key
        assert "" in registry.get_all()
        assert registry.get("") is handler


class TestRegistryPerformance:
    """Test performance characteristics of TaskHandlerRegistry."""

    def test_large_number_of_handlers(self, registry):
        """Test registry with many handlers."""
        handlers = []
        
        # Create many handlers
        for i in range(100):
            class DynamicHandler(TaskHandler):
                def __init__(self, handler_id):
                    self.handler_id = handler_id
                    
                @property
                def name(self) -> str:
                    return f"handler_{self.handler_id}"
                    
                async def process_task(self, task_id, message, session_id=None):
                    yield f"response_{self.handler_id}"
            
            handler = DynamicHandler(i)
            handlers.append(handler)
            registry.register(handler)
        
        # All should be registered
        assert len(registry.get_all()) == 100
        
        # Getting handlers should be fast
        import time
        start = time.time()
        for i in range(100):
            handler = registry.get(f"handler_{i}")
            assert handler is handlers[i]
        end = time.time()
        
        # Should be very fast (< 10ms for 100 lookups)
        assert (end - start) < 0.01

    def test_repeated_operations(self, registry, sample_handlers):
        """Test performance of repeated operations."""
        handler1 = sample_handlers["handler1"]
        handler2 = sample_handlers["handler2"]
        
        registry.register(handler1)
        registry.register(handler2)
        
        # Repeated get operations should be fast
        import time
        start = time.time()
        for _ in range(1000):
            registry.get("handler1")
            registry.get("handler2")
            registry.get()  # default
        end = time.time()
        
        # Should complete quickly
        assert (end - start) < 0.1


class TestRegistryIntegration:
    """Integration tests for TaskHandlerRegistry."""

    def test_with_task_manager_pattern(self, registry):
        """Test registry usage pattern similar to TaskManager."""
        from a2a_server.tasks.handlers.echo_handler import EchoHandler
        
        # Simulate TaskManager usage pattern
        echo_handler = EchoHandler()
        test_handler = TestHandler1()
        
        # Register handlers like TaskManager would
        registry.register(echo_handler, default=True)
        registry.register(test_handler)
        
        # Simulate handler resolution
        def resolve_handler(name=None):
            if name is None:
                return registry.get()
            return registry.get(name)
        
        # Test resolution
        assert resolve_handler() is echo_handler  # default
        assert resolve_handler("echo") is echo_handler
        assert resolve_handler("handler1") is test_handler
        
        # Test getting available handlers
        available = registry.get_all()
        assert len(available) == 2
        assert set(available.keys()) == {"echo", "handler1"}


if __name__ == "__main__":
    # Manual test runner for development
    def manual_test():
        registry = TaskHandlerRegistry()
        
        handler1 = TestHandler1()
        handler2 = TestHandler2()
        
        print("Testing TaskHandlerRegistry...")
        
        # Register handlers
        registry.register(handler1)
        registry.register(handler2, default=True)
        
        print(f"Registered handlers: {list(registry.get_all().keys())}")
        print(f"Default handler: {registry.get().name}")
        print(f"Handler1: {registry.get('handler1').name}")
        print(f"Handler2: {registry.get('handler2').name}")
        
        print("Test completed!")
    
    # Uncomment to run manual test
    # manual_test()