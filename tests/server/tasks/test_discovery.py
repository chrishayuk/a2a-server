import pytest
import sys
import os
import logging
from unittest.mock import patch, MagicMock, Mock

from a2a.server.tasks.discovery import (
    discover_handlers_in_package,
    load_handlers_from_entry_points,
    discover_all_handlers,
    register_discovered_handlers
)
from a2a.server.tasks.task_handler import TaskHandler


class MockTaskHandler(TaskHandler):
    """Mock TaskHandler for testing discovery."""
    
    @property
    def name(self) -> str:
        return "mock_handler"
        
    async def process_task(self, task_id, message, session_id=None):
        yield


class MockTaskHandler2(TaskHandler):
    """Second Mock TaskHandler for testing discovery."""
    
    @property
    def name(self) -> str:
        return "mock_handler2"
        
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


# Setup for logging during tests
@pytest.fixture(autouse=True)
def setup_logging():
    # Configure logging to show debug messages
    logging.basicConfig(level=logging.DEBUG)
    yield
    # Reset logging after test
    logging.basicConfig(level=logging.WARNING)


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
    with patch("a2a.server.tasks.discovery.pkgutil.walk_packages", fake_walk_packages):
        with patch("a2a.server.tasks.discovery.importlib.import_module", return_value=mock_module):
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
        with patch("a2a.server.tasks.discovery.importlib.metadata.entry_points", 
                return_value=mock_entry_points):
            handlers = list(load_handlers_from_entry_points())
    else:
        # Mock unsuccessful importlib import
        import_error = ImportError("No module named 'importlib.metadata'")
        with patch("a2a.server.tasks.discovery.importlib.metadata.entry_points",
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
    
    with patch("a2a.server.tasks.discovery.discover_handlers_in_package", 
              return_value=[mock_package_handler]):
        with patch("a2a.server.tasks.discovery.load_handlers_from_entry_points", 
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


def test_register_discovered_handlers():
    """Test the registration of discovered handlers with the TaskManager."""
    
    # Create mock handlers
    mock_handler1 = MockTaskHandler()
    mock_handler2_cls = MockTaskHandler2
    
    # Mock task manager
    mock_task_manager = MagicMock()
    mock_task_manager.register_handler = MagicMock()
    
    # Mock handler discovery to return our classes
    with patch("a2a.server.tasks.discovery.discover_all_handlers", 
              return_value=[MockTaskHandler, mock_handler2_cls]):
        
        # Test with default settings
        register_discovered_handlers(mock_task_manager)
        
        # The first handler should be registered as default
        assert mock_task_manager.register_handler.call_count == 2
        first_call_args = mock_task_manager.register_handler.call_args_list[0]
        assert isinstance(first_call_args[0][0], MockTaskHandler)
        assert first_call_args[1]["default"] is True
        
        second_call_args = mock_task_manager.register_handler.call_args_list[1]
        assert isinstance(second_call_args[0][0], MockTaskHandler2)
        assert second_call_args[1]["default"] is False
        
        # Reset mock
        mock_task_manager.reset_mock()
        
        # Test with specified default handler
        register_discovered_handlers(
            mock_task_manager, 
            default_handler_class=mock_handler2_cls
        )
        
        # The specified handler should be registered as default
        assert mock_task_manager.register_handler.call_count == 2
        first_call_args = mock_task_manager.register_handler.call_args_list[0]
        assert isinstance(first_call_args[0][0], MockTaskHandler)
        assert first_call_args[1]["default"] is False
        
        second_call_args = mock_task_manager.register_handler.call_args_list[1]
        assert isinstance(second_call_args[0][0], MockTaskHandler2)
        assert second_call_args[1]["default"] is True
        
        # Reset mock
        mock_task_manager.reset_mock()
        
        # Test with empty discovery results
        with patch("a2a.server.tasks.discovery.discover_all_handlers", return_value=[]):
            register_discovered_handlers(mock_task_manager)
            # Should not register any handlers
            assert mock_task_manager.register_handler.call_count == 0


def test_register_discovered_handlers_with_error():
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
    
    # Mock task manager
    mock_task_manager = MagicMock()
    
    # Mock handler discovery to return our error-prone class and a good one
    with patch("a2a.server.tasks.discovery.discover_all_handlers", 
              return_value=[ErrorHandler, MockTaskHandler]):
        
        # Should continue after error and register the good handler
        register_discovered_handlers(mock_task_manager)
        
        # Only the good handler should be registered
        assert mock_task_manager.register_handler.call_count == 1
        call_args = mock_task_manager.register_handler.call_args
        assert isinstance(call_args[0][0], MockTaskHandler)
        assert call_args[1]["default"] is True