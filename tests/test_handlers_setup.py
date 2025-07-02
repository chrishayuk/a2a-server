#!/usr/bin/env python3
# tests/test_handlers_setup.py
"""
Comprehensive unit tests for a2a_server.handlers_setup module.

Tests the handler discovery, instantiation, and configuration including:
- Handler class discovery by import path and class name
- Object loading with various patterns
- Parameter preparation and validation
- Handler instantiation and configuration
- Error handling and edge cases
"""

import pytest
import importlib
import inspect
from unittest.mock import Mock, patch, MagicMock
from typing import Any, Dict, List, Optional, Type

from a2a_server.handlers_setup import (
    find_handler_class,
    load_object,
    prepare_params,
    setup_handlers,
)


# Mock TaskHandler for testing
class MockTaskHandler:
    """Mock base TaskHandler class for testing."""
    
    def __init__(self, name: str = "mock", **kwargs):
        self.name = name
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestFindHandlerClass:
    """Test the find_handler_class function."""

    @patch('a2a_server.handlers_setup.importlib.import_module')
    def test_find_handler_class_by_fully_qualified_path(self, mock_import):
        """Test finding handler class by fully qualified import path."""
        # Create mock module and class
        mock_module = Mock()
        mock_class = Mock()
        mock_class.__name__ = "TestHandler"
        
        # Make it a subclass of TaskHandler
        def mock_issubclass(cls, base):
            return cls is mock_class
        
        mock_module.TestHandler = mock_class
        mock_import.return_value = mock_module
        
        with patch('a2a_server.handlers_setup.issubclass', side_effect=mock_issubclass):
            result = find_handler_class("a2a_server.handlers.test_handler.TestHandler")
            
            assert result is mock_class
            mock_import.assert_called_once_with("a2a_server.handlers.test_handler")

    @patch('a2a_server.handlers_setup.importlib.import_module')
    def test_find_handler_class_import_error(self, mock_import):
        """Test handling of import errors for fully qualified paths."""
        mock_import.side_effect = ImportError("Module not found")
        
        with patch('a2a_server.handlers_setup.logging') as mock_logging:
            result = find_handler_class("nonexistent.module.Handler")
            
            assert result is None
            mock_logging.error.assert_called_once()

    @patch('a2a_server.handlers_setup.discover_all_handlers')
    def test_find_handler_class_by_discovery(self, mock_discover):
        """Test finding handler class through discovery."""
        mock_class1 = Mock()
        mock_class1.__name__ = "WeatherHandler"
        mock_class2 = Mock()
        mock_class2.__name__ = "ChatHandler"
        
        mock_discover.return_value = [mock_class1, mock_class2]
        
        result = find_handler_class("ChatHandler")
        assert result is mock_class2

    @patch('a2a_server.handlers_setup.discover_all_handlers')
    def test_find_handler_class_not_found_in_discovery(self, mock_discover):
        """Test when class is not found in discovery."""
        mock_class = Mock()
        mock_class.__name__ = "ExistingHandler"
        mock_discover.return_value = [mock_class]
        
        with patch('a2a_server.handlers_setup.pkgutil.walk_packages') as mock_walk:
            with patch('a2a_server.handlers_setup.importlib.import_module') as mock_import:
                # Mock package walking fallback
                mock_walk.return_value = [
                    (None, "a2a_server.tasks.handlers.test_handler", None)
                ]
                
                mock_module = Mock()
                mock_target_class = Mock()
                mock_target_class.__name__ = "NonExistentHandler"
                
                def mock_issubclass(cls, base):
                    return cls is mock_target_class
                
                mock_module.__dict__ = {"NonExistentHandler": mock_target_class}
                mock_import.return_value = mock_module
                
                with patch('a2a_server.handlers_setup.inspect.getmembers') as mock_getmembers:
                    with patch('a2a_server.handlers_setup.issubclass', side_effect=mock_issubclass):
                        mock_getmembers.return_value = [("NonExistentHandler", mock_target_class)]
                        
                        result = find_handler_class("NonExistentHandler")
                        assert result is mock_target_class

    @patch('a2a_server.handlers_setup.discover_all_handlers')
    @patch('a2a_server.handlers_setup.pkgutil.walk_packages')
    @patch('a2a_server.handlers_setup.logging')
    def test_find_handler_class_not_found_anywhere(self, mock_logging, mock_walk, mock_discover):
        """Test when handler class is not found anywhere."""
        mock_discover.return_value = []
        mock_walk.return_value = []
        
        result = find_handler_class("NonExistentHandler")
        
        assert result is None
        mock_logging.error.assert_called_with("Handler class not found: %s", "NonExistentHandler")


class TestLoadObject:
    """Test the load_object function."""

    @patch('a2a_server.handlers_setup.importlib.import_module')
    def test_load_object_fully_qualified_path(self, mock_import):
        """Test loading object with fully qualified dotted path."""
        mock_module = Mock()
        mock_object = Mock()
        mock_module.target_object = mock_object
        mock_import.return_value = mock_module
        
        result = load_object("module.path.target_object")
        
        assert result is mock_object
        mock_import.assert_called_once_with("module.path")

    @patch('a2a_server.handlers_setup.importlib.import_module')
    def test_load_object_pattern_matching(self, mock_import):
        """Test loading object with pattern matching."""
        # First few patterns fail
        mock_import.side_effect = [
            ImportError(),  # spec itself
            ImportError(),  # f"{spec}.{spec}"
            ImportError(),  # f"{spec}_agent"
            ImportError(),  # f"{spec}_agent.{spec}"
            ImportError(),  # f"agents.{spec}"
        ]
        
        # Last pattern succeeds
        mock_module = Mock()
        mock_module.agent = "found_agent"
        mock_import.side_effect.append(mock_module)
        
        result = load_object("test_agent")
        
        assert result == "found_agent"
        # Should have tried multiple patterns
        assert mock_import.call_count == 6

    @patch('a2a_server.handlers_setup.importlib.import_module')
    def test_load_object_dotted_pattern_with_attribute(self, mock_import):
        """Test loading object with dotted pattern that has attribute."""
        def mock_import_func(module_name):
            if module_name == "test_agent":
                mock_module = Mock()
                mock_module.test_agent = "found_object"
                return mock_module
            raise ImportError()
        
        mock_import.side_effect = mock_import_func
        
        result = load_object("test_agent")
        
        assert result == "found_object"

    @patch('a2a_server.handlers_setup.importlib.import_module')
    def test_load_object_not_found(self, mock_import):
        """Test when object cannot be found anywhere."""
        mock_import.side_effect = ImportError("Not found")
        
        with pytest.raises(ImportError, match="Could not locate object 'nonexistent'"):
            load_object("nonexistent")


class TestPrepareParams:
    """Test the prepare_params function."""

    def test_prepare_params_basic_filtering(self):
        """Test basic parameter filtering based on class signature."""
        class TestHandler:
            def __init__(self, name: str, valid_param: str, another_param: int = 10):
                pass
        
        config = {
            "name": "test_handler",
            "type": "TestHandler",
            "agent_card": {"name": "Test"},
            "valid_param": "value1",
            "another_param": 20,
            "invalid_param": "should_be_filtered"
        }
        
        result = prepare_params(TestHandler, config)
        
        expected = {
            "name": "test_handler",
            "valid_param": "value1",
            "another_param": 20
        }
        assert result == expected

    @patch('a2a_server.handlers_setup.load_object')
    def test_prepare_params_string_loading(self, mock_load_object):
        """Test that string parameters (except name) are loaded as objects."""
        class TestHandler:
            def __init__(self, agent: Any, name: str):
                pass
        
        mock_agent = Mock()
        mock_load_object.return_value = mock_agent
        
        config = {
            "name": "test_handler",  # Should not be loaded
            "agent": "path.to.agent",  # Should be loaded
        }
        
        result = prepare_params(TestHandler, config)
        
        assert result["name"] == "test_handler"
        assert result["agent"] is mock_agent
        mock_load_object.assert_called_once_with("path.to.agent")

    @patch('a2a_server.handlers_setup.load_object')
    @patch('a2a_server.handlers_setup.logging')
    def test_prepare_params_string_loading_failure(self, mock_logging, mock_load_object):
        """Test handling of string loading failures."""
        class TestHandler:
            def __init__(self, agent: Any):
                pass
        
        mock_load_object.side_effect = ImportError("Cannot load")
        
        config = {
            "agent": "invalid.path"
        }
        
        result = prepare_params(TestHandler, config)
        
        # Should fallback to original string value
        assert result["agent"] == "invalid.path"
        mock_load_object.assert_called_once_with("invalid.path")

    def test_prepare_params_non_string_values(self):
        """Test that non-string values are passed through unchanged."""
        class TestHandler:
            def __init__(self, config: dict, count: int, flag: bool):
                pass
        
        config = {
            "config": {"key": "value"},
            "count": 42,
            "flag": True
        }
        
        result = prepare_params(TestHandler, config)
        
        assert result == config

    def test_prepare_params_empty_config(self):
        """Test with empty configuration."""
        class TestHandler:
            def __init__(self, optional_param: str = "default"):
                pass
        
        result = prepare_params(TestHandler, {})
        
        assert result == {}


class TestSetupHandlers:
    """Test the setup_handlers function."""

    @patch('a2a_server.handlers_setup.find_handler_class')
    @patch('a2a_server.handlers_setup.prepare_params')
    def test_setup_handlers_basic(self, mock_prepare_params, mock_find_handler_class):
        """Test basic handler setup."""
        # Mock handler class
        mock_handler_class = Mock()
        mock_handler_instance = Mock()
        mock_handler_class.return_value = mock_handler_instance
        mock_find_handler_class.return_value = mock_handler_class
        
        # Mock parameter preparation
        mock_prepare_params.return_value = {"name": "test_handler"}
        
        handlers_config = {
            "default_handler": "test_handler",
            "test_handler": {
                "type": "TestHandler",
                "param": "value"
            }
        }
        
        all_handlers, default_handler = setup_handlers(handlers_config)
        
        assert len(all_handlers) == 1
        assert all_handlers[0] is mock_handler_instance
        assert default_handler is mock_handler_instance
        
        mock_find_handler_class.assert_called_once_with("TestHandler")
        mock_prepare_params.assert_called_once()
        mock_handler_class.assert_called_once_with(name="test_handler")

    @patch('a2a_server.handlers_setup.find_handler_class')
    def test_setup_handlers_with_agent_card(self, mock_find_handler_class):
        """Test handler setup with agent_card attachment."""
        mock_handler_class = Mock()
        mock_handler_instance = Mock()
        mock_handler_class.return_value = mock_handler_instance
        mock_find_handler_class.return_value = mock_handler_class
        
        handlers_config = {
            "test_handler": {
                "type": "TestHandler",
                "agent_card": {"name": "Test Agent"}
            }
        }
        
        with patch('a2a_server.handlers_setup.prepare_params') as mock_prepare_params:
            mock_prepare_params.return_value = {"name": "test_handler"}
            
            with patch('a2a_server.handlers_setup.logging') as mock_logging:
                all_handlers, default_handler = setup_handlers(handlers_config)
                
                assert len(all_handlers) == 1
                assert hasattr(mock_handler_instance, 'agent_card')
                assert mock_handler_instance.agent_card == {"name": "Test Agent"}
                mock_logging.debug.assert_called()

    @patch('a2a_server.handlers_setup.find_handler_class')
    def test_setup_handlers_missing_type(self, mock_find_handler_class):
        """Test handling of handler config without type."""
        handlers_config = {
            "invalid_handler": {
                "param": "value"
                # No "type" field
            }
        }
        
        with patch('a2a_server.handlers_setup.logging') as mock_logging:
            all_handlers, default_handler = setup_handlers(handlers_config)
            
            assert len(all_handlers) == 0
            assert default_handler is None
            mock_logging.warning.assert_called_with("Handler %s missing type", "invalid_handler")
            mock_find_handler_class.assert_not_called()

    @patch('a2a_server.handlers_setup.find_handler_class')
    def test_setup_handlers_class_not_found(self, mock_find_handler_class):
        """Test handling when handler class cannot be found."""
        mock_find_handler_class.return_value = None
        
        handlers_config = {
            "missing_handler": {
                "type": "NonExistentHandler"
            }
        }
        
        all_handlers, default_handler = setup_handlers(handlers_config)
        
        assert len(all_handlers) == 0
        assert default_handler is None
        mock_find_handler_class.assert_called_once_with("NonExistentHandler")

    @patch('a2a_server.handlers_setup.find_handler_class')
    @patch('a2a_server.handlers_setup.prepare_params')
    def test_setup_handlers_instantiation_error(self, mock_prepare_params, mock_find_handler_class):
        """Test handling of handler instantiation errors."""
        mock_handler_class = Mock()
        mock_handler_class.side_effect = ValueError("Instantiation failed")
        mock_find_handler_class.return_value = mock_handler_class
        mock_prepare_params.return_value = {"name": "error_handler"}
        
        handlers_config = {
            "error_handler": {
                "type": "ErrorHandler"
            }
        }
        
        with patch('a2a_server.handlers_setup.logging') as mock_logging:
            all_handlers, default_handler = setup_handlers(handlers_config)
            
            assert len(all_handlers) == 0
            assert default_handler is None
            mock_logging.error.assert_called()

    def test_setup_handlers_skips_metadata(self):
        """Test that metadata keys are properly skipped."""
        handlers_config = {
            "use_discovery": True,
            "handler_packages": ["package"],
            "default_handler": "test",
            "test_handler": {
                "type": "TestHandler"
            }
        }
        
        with patch('a2a_server.handlers_setup.find_handler_class') as mock_find:
            mock_handler_class = Mock()
            mock_find.return_value = mock_handler_class
            
            with patch('a2a_server.handlers_setup.prepare_params') as mock_prepare:
                mock_prepare.return_value = {"name": "test_handler"}
                
                all_handlers, default_handler = setup_handlers(handlers_config)
                
                # Should only process test_handler, not metadata
                assert len(all_handlers) == 1
                mock_find.assert_called_once_with("TestHandler")

    def test_setup_handlers_skips_non_dict_configs(self):
        """Test that non-dictionary handler configs are skipped."""
        handlers_config = {
            "valid_handler": {
                "type": "ValidHandler"
            },
            "string_config": "not_a_dict",
            "list_config": ["also", "not", "dict"],
            "none_config": None
        }
        
        with patch('a2a_server.handlers_setup.find_handler_class') as mock_find:
            mock_handler_class = Mock()
            mock_find.return_value = mock_handler_class
            
            with patch('a2a_server.handlers_setup.prepare_params') as mock_prepare:
                mock_prepare.return_value = {"name": "valid_handler"}
                
                all_handlers, default_handler = setup_handlers(handlers_config)
                
                # Should only process valid_handler
                assert len(all_handlers) == 1
                mock_find.assert_called_once_with("ValidHandler")

    @patch('a2a_server.handlers_setup.find_handler_class')
    @patch('a2a_server.handlers_setup.prepare_params')
    def test_setup_handlers_multiple_handlers_with_default(self, mock_prepare_params, mock_find_handler_class):
        """Test setup with multiple handlers and default selection."""
        # Create different handler instances
        handler1 = Mock()
        handler1.name = "handler1"
        handler2 = Mock()
        handler2.name = "handler2"
        handler3 = Mock()
        handler3.name = "handler3"
        
        mock_handler_class = Mock()
        mock_handler_class.side_effect = [handler1, handler2, handler3]
        mock_find_handler_class.return_value = mock_handler_class
        
        def mock_prepare_side_effect(cls, cfg):
            return {"name": cfg["name"]}
        mock_prepare_params.side_effect = mock_prepare_side_effect
        
        handlers_config = {
            "default_handler": "handler2",
            "handler1": {"type": "Handler", "name": "handler1"},
            "handler2": {"type": "Handler", "name": "handler2"},
            "handler3": {"type": "Handler", "name": "handler3"}
        }
        
        all_handlers, default_handler = setup_handlers(handlers_config)
        
        assert len(all_handlers) == 3
        assert default_handler is handler2
        
        # Verify all handlers are in the list
        handler_names = [h.name for h in all_handlers]
        assert "handler1" in handler_names
        assert "handler2" in handler_names
        assert "handler3" in handler_names


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_end_to_end_handler_setup(self):
        """Test complete end-to-end handler setup flow."""
        # Mock a realistic handler class
        class MockRealisticHandler(MockTaskHandler):
            def __init__(self, name: str, agent: str, config: dict = None):
                super().__init__(name=name)
                self.agent = agent
                self.config = config or {}
        
        def mock_load_object(spec):
            if spec == "agents.weather":
                return "weather_agent_instance"
            raise ImportError(f"Cannot load {spec}")
        
        def mock_find_handler_class(name):
            if name == "WeatherHandler":
                return MockRealisticHandler
            return None
        
        handlers_config = {
            "default_handler": "weather",
            "weather": {
                "type": "WeatherHandler",
                "agent": "agents.weather",
                "config": {"api_key": "secret"},
                "agent_card": {
                    "name": "Weather Agent",
                    "description": "Provides weather information"
                }
            }
        }
        
        with patch('a2a_server.handlers_setup.find_handler_class', side_effect=mock_find_handler_class):
            with patch('a2a_server.handlers_setup.load_object', side_effect=mock_load_object):
                all_handlers, default_handler = setup_handlers(handlers_config)
                
                assert len(all_handlers) == 1
                handler = all_handlers[0]
                assert handler is default_handler
                
                # Verify handler properties
                assert handler.name == "weather"
                assert handler.agent == "weather_agent_instance"
                assert handler.config == {"api_key": "secret"}
                assert hasattr(handler, 'agent_card')
                assert handler.agent_card["name"] == "Weather Agent"


class TestErrorHandling:
    """Test comprehensive error handling scenarios."""

    @patch('a2a_server.handlers_setup.logging')
    def test_find_handler_class_attribute_error(self, mock_logging):
        """Test handling of AttributeError during class lookup."""
        with patch('a2a_server.handlers_setup.importlib.import_module') as mock_import:
            mock_module = Mock()
            del mock_module.NonExistentClass  # Simulate AttributeError
            mock_import.return_value = mock_module
            
            result = find_handler_class("module.NonExistentClass")
            
            assert result is None
            mock_logging.error.assert_called()

    def test_load_object_empty_string(self):
        """Test load_object with empty string."""
        with pytest.raises(ImportError):
            load_object("")

    def test_prepare_params_complex_signature(self):
        """Test prepare_params with complex method signature."""
        class ComplexHandler:
            def __init__(self, name: str, *args, **kwargs):
                pass
        
        config = {
            "name": "complex",
            "extra_arg": "value",
            "another_param": 42
        }
        
        # Should handle *args/**kwargs gracefully
        result = prepare_params(ComplexHandler, config)
        assert "name" in result

    @patch('a2a_server.handlers_setup.inspect.signature')
    def test_prepare_params_signature_error(self, mock_signature):
        """Test prepare_params when signature inspection fails."""
        mock_signature.side_effect = ValueError("Cannot inspect signature")
        
        class ProblematicHandler:
            def __init__(self):
                pass
        
        # Should handle signature inspection errors gracefully
        result = prepare_params(ProblematicHandler, {"param": "value"})
        assert isinstance(result, dict)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])