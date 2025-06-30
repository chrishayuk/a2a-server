import pytest
import sys
import os
import logging
from unittest.mock import patch, MagicMock, Mock, AsyncMock

from a2a_server.tasks.discovery import (
    discover_handlers_in_package,
    load_handlers_from_entry_points,
    discover_all_handlers,
    register_discovered_handlers,
    _register_explicit_handlers
)
from a2a_server.tasks.handlers.task_handler import TaskHandler


class MockTaskHandler(TaskHandler):
    """Mock TaskHandler for testing discovery."""
    
    def __init__(self, name="mock_handler", **kwargs):
        self._name = name
        
    @property
    def name(self) -> str:
        return self._name
        
    async def process_task(self, task_id, message, session_id=None):
        yield


class MockTaskHandler2(TaskHandler):
    """Second Mock TaskHandler for testing discovery."""
    
    def __init__(self, name="mock_handler2", **kwargs):
        self._name = name
        
    @property
    def name(self) -> str:
        return self._name
        
    async def process_task(self, task_id, message, session_id=None):
        yield


class MockAgentHandler(TaskHandler):
    """Mock agent-based handler for testing explicit registration."""
    
    def __init__(self, agent=None, name="mock_agent_handler", **kwargs):
        self._name = name
        self.agent = agent
        
    @property
    def name(self) -> str:
        return self._name
        
    async def process_task(self, task_id, message, session_id=None):
        yield


# Use our abstract property approach to mark as abstract
class AbstractMockHandler(TaskHandler):
    """Abstract handler that should be filtered out."""
    
    @property
    def name(self) -> str:
        return "abstract_handler"
    
    # Add this property to be checked in the implementation
    @property
    def abstract(self) -> bool:
        return True
        
    async def process_task(self, task_id, message, session_id=None):
        raise NotImplementedError()


# Mock agent classes for testing
class MockAgent:
    """Mock agent for testing agent-based handlers."""
    def __init__(self, enable_sessions=False, **kwargs):
        self.enable_sessions = enable_sessions
        self.config = kwargs
        

def mock_agent_factory(**kwargs):
    """Mock agent factory function."""
    return MockAgent(**kwargs)


# Setup for logging during tests
@pytest.fixture(autouse=True)
def setup_logging():
    # Configure logging to show debug messages
    logging.basicConfig(level=logging.DEBUG)
    yield
    # Reset logging after test
    logging.basicConfig(level=logging.WARNING)


@pytest.fixture
def mock_task_manager():
    """Fixture for mock task manager."""
    manager = MagicMock()
    manager.register_handler = MagicMock()
    return manager


def test_discover_handlers_in_package_empty():
    """Test discovery with non-existent package."""
    handlers = list(discover_handlers_in_package("nonexistent_package"))
    assert handlers == []


def test_discover_handlers_in_package_with_mocks():
    """Test discovery with mock package."""
    
    # Create a simple fake module with our handler classes
    class MockModule:
        def __init__(self):
            self.__path__ = ["/fake/path"]
            self.__name__ = "mock_package"
            self.MockTaskHandler = MockTaskHandler
            self.MockTaskHandler2 = MockTaskHandler2
            self.AbstractMockHandler = AbstractMockHandler
            self.NotAHandler = object  # Should be ignored

    mock_module = MockModule()
    
    # Create a fake package hierarchy
    sys.modules["mock_package"] = mock_module
    sys.modules["mock_package.submodule"] = mock_module
    
    # Create a simple mock for pkgutil.walk_packages
    def fake_walk_packages(path, prefix):
        yield None, "mock_package.submodule", False
    
    # Patch necessary functions
    with patch("a2a_server.tasks.discovery.pkgutil.walk_packages", fake_walk_packages):
        with patch("a2a_server.tasks.discovery.importlib.import_module", return_value=mock_module):
            handlers = list(discover_handlers_in_package("mock_package"))
    
    # Clean up
    del sys.modules["mock_package"]
    del sys.modules["mock_package.submodule"]
    
    # We should find exactly two handlers (excluding abstract and non-handler classes)
    assert len(handlers) == 2
    assert MockTaskHandler in handlers
    assert MockTaskHandler2 in handlers
    assert AbstractMockHandler not in handlers


@pytest.mark.parametrize("python_version,use_importlib", [
    ("3.9", False),  # Use pkg_resources
    ("3.10", True),  # Use importlib.metadata
])
def test_load_handlers_from_entry_points(python_version, use_importlib):
    """Test loading handlers from entry points."""
    
    # Create mock entry points
    class MockEntryPoint:
        def __init__(self, name, handler_class):
            self.name = name
            self._handler_class = handler_class
            
        def load(self):
            if isinstance(self._handler_class, Exception):
                raise self._handler_class
            return self._handler_class
    
    mock_entry_points = [
        MockEntryPoint("mock_handler", MockTaskHandler),
        MockEntryPoint("mock_handler2", MockTaskHandler2),
        MockEntryPoint("abstract_handler", AbstractMockHandler),
        MockEntryPoint("error_handler", ImportError("Simulated import error")),
    ]
    
    # Setup mocks based on Python version
    if use_importlib:
        with patch("a2a_server.tasks.discovery.importlib.metadata.entry_points", 
                return_value=mock_entry_points):
            handlers = list(load_handlers_from_entry_points())
    else:
        # Mock unsuccessful importlib import
        import_error = ImportError("No module named 'importlib.metadata'")
        with patch("a2a_server.tasks.discovery.importlib.metadata.entry_points",
                side_effect=import_error):
            # Then mock pkg_resources
            with patch("pkg_resources.iter_entry_points", return_value=mock_entry_points):
                handlers = list(load_handlers_from_entry_points())
    
    # We should find exactly two valid handlers (the abstract one should be filtered out)
    assert len(handlers) == 2
    assert MockTaskHandler in handlers
    assert MockTaskHandler2 in handlers
    assert AbstractMockHandler not in handlers


def test_discover_all_handlers():
    """Test the main discover_all_handlers function."""
    
    # Mock both discovery mechanisms
    mock_package_handler = MockTaskHandler
    mock_entrypoint_handler = MockTaskHandler2
    
    with patch("a2a_server.tasks.discovery.discover_handlers_in_package", 
              return_value=[mock_package_handler]):
        with patch("a2a_server.tasks.discovery.load_handlers_from_entry_points", 
                  return_value=[mock_entrypoint_handler]):
            
            # Default package
            handlers = discover_all_handlers()
            assert len(handlers) == 2
            assert mock_package_handler in handlers
            assert mock_entrypoint_handler in handlers
            
            # Custom package
            handlers = discover_all_handlers(packages=["custom.package"])
            assert len(handlers) == 2
            assert mock_package_handler in handlers
            assert mock_entrypoint_handler in handlers


def test_register_discovered_handlers_package_discovery(mock_task_manager):
    """Test the registration of discovered handlers with the TaskManager."""
    
    # Mock handler discovery to return our classes
    with patch("a2a_server.tasks.discovery.discover_all_handlers", 
              return_value=[MockTaskHandler, MockTaskHandler2]):
        
        # Test with default settings (package discovery)
        register_discovered_handlers(mock_task_manager, packages=["test.package"])
        
        # Both handlers should be registered
        assert mock_task_manager.register_handler.call_count == 2
        first_call_args = mock_task_manager.register_handler.call_args_list[0]
        assert isinstance(first_call_args[0][0], MockTaskHandler)
        assert first_call_args[1]["default"] is True  # First one becomes default
        
        second_call_args = mock_task_manager.register_handler.call_args_list[1]
        assert isinstance(second_call_args[0][0], MockTaskHandler2)
        assert second_call_args[1]["default"] is False
        
        # Reset mock
        mock_task_manager.reset_mock()
        
        # Test with specified default handler
        register_discovered_handlers(
            mock_task_manager, 
            packages=["test.package"],
            default_handler_class=MockTaskHandler2
        )
        
        # The specified handler should be registered as default
        assert mock_task_manager.register_handler.call_count == 2
        first_call_args = mock_task_manager.register_handler.call_args_list[0]
        assert isinstance(first_call_args[0][0], MockTaskHandler)
        assert first_call_args[1]["default"] is False
        
        second_call_args = mock_task_manager.register_handler.call_args_list[1]
        assert isinstance(second_call_args[0][0], MockTaskHandler2)
        assert second_call_args[1]["default"] is True


def test_register_discovered_handlers_with_error(mock_task_manager):
    """Test handler registration when instantiation fails."""
    
    # Create a handler class that raises an exception when instantiated
    class ErrorHandler(TaskHandler):
        def __init__(self):
            raise RuntimeError("Simulated error")
            
        @property
        def name(self) -> str:
            return "error_handler"
            
        async def process_task(self, task_id, message, session_id=None):
            yield
    
    # Mock handler discovery to return our error-prone class and a good one
    with patch("a2a_server.tasks.discovery.discover_all_handlers", 
              return_value=[ErrorHandler, MockTaskHandler]):
        
        # Should continue after error and register the good handler
        register_discovered_handlers(mock_task_manager, packages=["test.package"])
        
        # Only the good handler should be registered
        assert mock_task_manager.register_handler.call_count == 1
        call_args = mock_task_manager.register_handler.call_args
        assert isinstance(call_args[0][0], MockTaskHandler)
        assert call_args[1]["default"] is True


def test_explicit_handler_registration_simple(mock_task_manager):
    """Test explicit handler registration with simple configuration."""
    
    explicit_handlers = {
        "test_handler": {
            "type": "test_module.MockTaskHandler",
            "name": "test_handler"
        }
    }
    
    # Mock the import of handler class
    with patch("a2a_server.tasks.discovery.importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MockTaskHandler = MockTaskHandler
        mock_import.return_value = mock_module
        
        # Call the explicit registration function
        _register_explicit_handlers(mock_task_manager, explicit_handlers)
        
        # Verify handler was registered
        assert mock_task_manager.register_handler.call_count == 1
        call_args = mock_task_manager.register_handler.call_args
        assert isinstance(call_args[0][0], MockTaskHandler)
        assert call_args[1]["default"] is True  # First handler becomes default


def test_explicit_handler_registration_with_agent(mock_task_manager):
    """Test explicit handler registration with agent factory."""
    
    explicit_handlers = {
        "agent_handler": {
            "type": "test_module.MockAgentHandler", 
            "agent": "test_module.mock_agent_factory",
            "name": "agent_handler",
            "enable_sessions": True,
            "provider": "openai",
            "model": "gpt-4"
        }
    }
    
    # Mock the imports
    with patch("a2a_server.tasks.discovery.importlib.import_module") as mock_import:
        # Mock handler class import
        def side_effect(module_name):
            mock_module = MagicMock()
            if "MockAgentHandler" in module_name or module_name == "test_module":
                mock_module.MockAgentHandler = MockAgentHandler
                mock_module.mock_agent_factory = mock_agent_factory
            return mock_module
        
        mock_import.side_effect = side_effect
        
        # Call the explicit registration function
        _register_explicit_handlers(mock_task_manager, explicit_handlers)
        
        # Verify handler was registered
        assert mock_task_manager.register_handler.call_count == 1
        call_args = mock_task_manager.register_handler.call_args
        handler_instance = call_args[0][0]
        
        assert isinstance(handler_instance, MockAgentHandler)
        assert hasattr(handler_instance, 'agent')
        assert isinstance(handler_instance.agent, MockAgent)
        assert handler_instance.agent.enable_sessions is True


def test_explicit_handler_registration_agent_config_passing(mock_task_manager):
    """Test that agent configuration parameters are properly passed to factory functions."""
    
    explicit_handlers = {
        "configured_agent": {
            "type": "test_module.MockAgentHandler",
            "agent": "test_module.mock_agent_factory", 
            "name": "configured_agent",
            # Agent configuration parameters
            "enable_sessions": True,
            "infinite_context": True,
            "token_threshold": 2000,
            "provider": "anthropic",
            "model": "claude-3-sonnet",
            "streaming": True,
            # Handler configuration parameters  
            "sandbox_id": "test_sandbox",
            "session_sharing": True
        }
    }
    
    # Create a mock factory that records what parameters it receives
    received_params = {}
    
    def recording_agent_factory(**kwargs):
        received_params.update(kwargs)
        return MockAgent(**kwargs)
    
    # Mock the imports
    with patch("a2a_server.tasks.discovery.importlib.import_module") as mock_import:
        def side_effect(module_name):
            mock_module = MagicMock()
            if "MockAgentHandler" in module_name or module_name == "test_module":
                mock_module.MockAgentHandler = MockAgentHandler
                mock_module.mock_agent_factory = recording_agent_factory
            return mock_module
        
        mock_import.side_effect = side_effect
        
        # Call the explicit registration function
        _register_explicit_handlers(mock_task_manager, explicit_handlers)
        
        # Verify the agent factory received the correct parameters
        expected_agent_params = {
            "enable_sessions": True,
            "infinite_context": True, 
            "token_threshold": 2000,
            "provider": "anthropic",
            "model": "claude-3-sonnet",
            "streaming": True
        }
        
        for key, value in expected_agent_params.items():
            assert key in received_params
            assert received_params[key] == value
        
        # Verify handler was registered
        assert mock_task_manager.register_handler.call_count == 1
        call_args = mock_task_manager.register_handler.call_args
        handler_instance = call_args[0][0]
        
        assert isinstance(handler_instance, MockAgentHandler)
        assert handler_instance.agent.enable_sessions is True


def test_explicit_handler_registration_error_handling(mock_task_manager):
    """Test error handling in explicit handler registration."""
    
    explicit_handlers = {
        "missing_type": {
            "agent": "some.agent",
            "name": "missing_type"
            # Missing 'type' field
        },
        "import_error": {
            "type": "nonexistent.module.Handler",
            "name": "import_error"
        },
        "factory_error": {
            "type": "test_module.MockAgentHandler",
            "agent": "test_module.error_factory",
            "name": "factory_error"
        }
    }
    
    def error_factory(**kwargs):
        raise ValueError("Simulated factory error")
    
    # Mock the imports with mixed success/failure
    with patch("a2a_server.tasks.discovery.importlib.import_module") as mock_import:
        def side_effect(module_name):
            if "nonexistent" in module_name:
                raise ImportError("Module not found")
            
            mock_module = MagicMock()
            mock_module.MockAgentHandler = MockAgentHandler
            mock_module.error_factory = error_factory
            return mock_module
        
        mock_import.side_effect = side_effect
        
        # Call the explicit registration function
        _register_explicit_handlers(mock_task_manager, explicit_handlers)
        
        # No handlers should be registered due to errors
        assert mock_task_manager.register_handler.call_count == 0


def test_register_discovered_handlers_explicit_only(mock_task_manager):
    """Test registration with only explicit handlers (no package discovery)."""
    
    explicit_handlers = {
        "explicit_handler": {
            "type": "test_module.MockTaskHandler",
            "name": "explicit_handler"
        }
    }
    
    # Mock the import
    with patch("a2a_server.tasks.discovery.importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MockTaskHandler = MockTaskHandler
        mock_import.return_value = mock_module
        
        # Call with explicit handlers but no packages
        register_discovered_handlers(
            mock_task_manager,
            packages=None,  # No package discovery
            **explicit_handlers
        )
        
        # Should register the explicit handler
        assert mock_task_manager.register_handler.call_count == 1
        call_args = mock_task_manager.register_handler.call_args
        assert isinstance(call_args[0][0], MockTaskHandler)


def test_register_discovered_handlers_mixed(mock_task_manager):
    """Test registration with both explicit handlers and package discovery."""
    
    explicit_handlers = {
        "explicit_handler": {
            "type": "test_module.MockTaskHandler",
            "name": "explicit_handler"
        }
    }
    
    # Mock package discovery and explicit registration
    with patch("a2a_server.tasks.discovery.discover_all_handlers", 
              return_value=[MockTaskHandler2]):
        with patch("a2a_server.tasks.discovery.importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_module.MockTaskHandler = MockTaskHandler
            mock_import.return_value = mock_module
            
            # Call with both explicit handlers and packages
            register_discovered_handlers(
                mock_task_manager,
                packages=["test.package"],
                **explicit_handlers
            )
            
            # Should register both explicit and discovered handlers
            assert mock_task_manager.register_handler.call_count == 2


def test_agent_caching_in_explicit_registration(mock_task_manager):
    """Test that agents are cached to prevent double creation."""
    
    # Same agent configuration used twice
    explicit_handlers = {
        "handler1": {
            "type": "test_module.MockAgentHandler",
            "agent": "test_module.mock_agent_factory",
            "name": "handler1",
            "enable_sessions": True
        },
        "handler2": {
            "type": "test_module.MockAgentHandler", 
            "agent": "test_module.mock_agent_factory",
            "name": "handler2",
            "enable_sessions": True  # Same config as handler1
        }
    }
    
    creation_count = 0
    
    def counting_agent_factory(**kwargs):
        nonlocal creation_count
        creation_count += 1
        return MockAgent(**kwargs)
    
    # Mock the imports
    with patch("a2a_server.tasks.discovery.importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MockAgentHandler = MockAgentHandler
        mock_module.mock_agent_factory = counting_agent_factory
        mock_import.return_value = mock_module
        
        # Call the explicit registration function
        _register_explicit_handlers(mock_task_manager, explicit_handlers)
        
        # Agent should only be created once due to caching
        assert creation_count == 1
        
        # But both handlers should be registered
        assert mock_task_manager.register_handler.call_count == 2