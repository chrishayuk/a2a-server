#!/usr/bin/env python3
# tests/test_session_store_factory.py
"""
Comprehensive unit tests for a2a_server.session_store_factory module.
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, Any

# Import the module under test
from a2a_server.session_store_factory import (
    get_session_factory,
    build_session_manager,
    build_session_store,
    setup_ai_session_storage,
    create_ai_session_manager,
    create_shared_ai_session_manager,
    create_isolated_ai_session_manager,
    get_session_provider,
    get_session_stats,
    reset_session_caches,
    validate_session_setup,
    _filter_session_config,
    AI_SESSION_MANAGER_PARAMS
)

# Import global variables for testing - need to access module globals
import a2a_server.session_store_factory as ssf_module


class TestSessionFactoryGlobals:
    """Test global state management and factory creation."""

    def setup_method(self):
        """Reset global state before each test."""
        reset_session_caches()

    def teardown_method(self):
        """Clean up after each test."""
        reset_session_caches()

    @patch('a2a_server.session_store_factory.factory_for_env')
    def test_get_session_factory_creates_singleton(self, mock_factory_for_env):
        """Test that get_session_factory creates and returns a singleton."""
        mock_factory = Mock()
        mock_factory_for_env.return_value = mock_factory

        # First call should create the factory
        factory1 = get_session_factory()
        assert factory1 is mock_factory
        mock_factory_for_env.assert_called_once()

        # Second call should return the same instance
        factory2 = get_session_factory()
        assert factory2 is factory1
        # factory_for_env should not be called again
        assert mock_factory_for_env.call_count == 1

    @patch.dict(os.environ, {'SESSION_PROVIDER': 'redis'})
    @patch('a2a_server.session_store_factory.factory_for_env')
    def test_get_session_factory_with_redis_backend(self, mock_factory_for_env):
        """Test factory creation with Redis backend."""
        mock_factory = Mock()
        mock_factory_for_env.return_value = mock_factory

        factory = get_session_factory()
        assert factory is mock_factory
        mock_factory_for_env.assert_called_once()

    def test_reset_session_caches(self):
        """Test that reset_session_caches clears global state."""
        # Set up some state using module reference
        ssf_module._session_managers['test'] = Mock()
        ssf_module._session_factory = Mock()

        # Reset should clear everything
        reset_session_caches()

        assert len(ssf_module._session_managers) == 0
        assert ssf_module._session_factory is None


class TestSessionManagerBuilding:
    """Test session manager creation and caching."""

    def setup_method(self):
        reset_session_caches()

    def teardown_method(self):
        reset_session_caches()

    @patch('a2a_server.session_store_factory.SessionManager')
    @patch('a2a_server.session_store_factory.server_sandbox')
    def test_build_session_manager_with_auto_sandbox_id(self, mock_server_sandbox, mock_session_manager):
        """Test building session manager with auto-generated sandbox ID."""
        mock_server_sandbox.return_value = 'auto-sandbox-123'
        mock_manager = Mock()
        mock_session_manager.return_value = mock_manager

        manager = build_session_manager()

        mock_server_sandbox.assert_called_once()
        mock_session_manager.assert_called_once_with(
            sandbox_id='auto-sandbox-123',
            default_ttl_hours=24
        )
        assert manager is mock_manager

    @patch('a2a_server.session_store_factory.SessionManager')
    def test_build_session_manager_with_explicit_sandbox_id(self, mock_session_manager):
        """Test building session manager with explicit sandbox ID."""
        mock_manager = Mock()
        mock_session_manager.return_value = mock_manager

        manager = build_session_manager(sandbox_id='test-sandbox', default_ttl_hours=48)

        mock_session_manager.assert_called_once_with(
            sandbox_id='test-sandbox',
            default_ttl_hours=48
        )
        assert manager is mock_manager

    @patch('a2a_server.session_store_factory.SessionManager')
    def test_build_session_manager_caching(self, mock_session_manager):
        """Test that session managers are cached by sandbox_id."""
        mock_manager1 = Mock()
        mock_manager2 = Mock()
        mock_session_manager.side_effect = [mock_manager1, mock_manager2]

        # First call should create and cache
        manager1 = build_session_manager(sandbox_id='test-sandbox')
        assert manager1 is mock_manager1

        # Second call with same sandbox_id should return cached
        manager2 = build_session_manager(sandbox_id='test-sandbox')
        assert manager2 is mock_manager1  # Same instance

        # Call with different sandbox_id should create new
        manager3 = build_session_manager(sandbox_id='different-sandbox')
        assert manager3 is mock_manager2

        # Only two SessionManager instances should be created
        assert mock_session_manager.call_count == 2

    @patch('a2a_server.session_store_factory.SessionManager')
    def test_build_session_manager_refresh(self, mock_session_manager):
        """Test that refresh=True forces new manager creation."""
        mock_manager1 = Mock()
        mock_manager2 = Mock()
        mock_session_manager.side_effect = [mock_manager1, mock_manager2]

        # Create initial manager
        manager1 = build_session_manager(sandbox_id='test-sandbox')
        assert manager1 is mock_manager1

        # Refresh should create new manager
        manager2 = build_session_manager(sandbox_id='test-sandbox', refresh=True)
        assert manager2 is mock_manager2
        assert manager2 is not manager1

    def test_build_session_store_alias(self):
        """Test that build_session_store is an alias for build_session_manager."""
        with patch('a2a_server.session_store_factory.build_session_manager') as mock_build:
            mock_manager = Mock()
            mock_build.return_value = mock_manager

            result = build_session_store(sandbox_id='test', default_ttl_hours=12, refresh=True)

            mock_build.assert_called_once_with(
                sandbox_id='test',
                default_ttl_hours=12,
                refresh=True
            )
            assert result is mock_manager


class TestAISessionStorage:
    """Test AI session storage setup and management."""

    def setup_method(self):
        reset_session_caches()

    @patch('a2a_server.utils.session_setup.SessionSetup.setup_ai_storage')
    def test_setup_ai_session_storage(self, mock_setup_ai_storage):
        """Test AI session storage setup."""
        mock_setup_ai_storage.return_value = 'final-sandbox-id'

        setup_ai_session_storage(sandbox_id='test-sandbox', default_ttl_hours=48)

        mock_setup_ai_storage.assert_called_once_with(
            sandbox_id='test-sandbox',
            default_ttl_hours=48
        )

    @patch('a2a_server.utils.session_setup.SessionSetup.setup_ai_storage')
    def test_setup_ai_session_storage_with_defaults(self, mock_setup_ai_storage):
        """Test AI session storage setup with default parameters."""
        mock_setup_ai_storage.return_value = 'default-sandbox'

        setup_ai_session_storage()

        mock_setup_ai_storage.assert_called_once_with(
            sandbox_id=None,
            default_ttl_hours=24
        )


class TestSessionConfigFiltering:
    """Test session configuration filtering for AI session managers."""

    def test_filter_session_config_keeps_supported_params(self):
        """Test that only supported parameters are kept."""
        config = {
            'sandbox_id': 'test-sandbox',
            'session_sharing': True,
            'enable_sessions': True,
            'streaming': False,
            'circuit_breaker_threshold': 10,  # Unsupported
            'invalid_param': 'value',         # Unsupported
            'token_threshold': 1000,
        }

        filtered = _filter_session_config(config)

        expected = {
            'sandbox_id': 'test-sandbox',
            'session_sharing': True,
            'enable_sessions': True,
            'streaming': False,
            'token_threshold': 1000,
        }
        assert filtered == expected

    def test_filter_session_config_empty_input(self):
        """Test filtering with empty configuration."""
        assert _filter_session_config({}) == {}

    def test_filter_session_config_no_supported_params(self):
        """Test filtering when no supported parameters are present."""
        config = {
            'unsupported1': 'value1',
            'unsupported2': 'value2',
        }
        assert _filter_session_config(config) == {}

    def test_ai_session_manager_params_constant(self):
        """Test that AI_SESSION_MANAGER_PARAMS contains expected values."""
        expected_params = {
            'sandbox_id', 'session_sharing', 'shared_sandbox_group',
            'enable_sessions', 'infinite_context', 'token_threshold',
            'max_turns_per_segment', 'session_ttl_hours', 'streaming'
        }
        
        # Check that all expected params are present
        for param in expected_params:
            assert param in AI_SESSION_MANAGER_PARAMS


class TestAISessionManagerCreation:
    """Test AI session manager creation functions."""

    @patch('a2a_server.utils.session_setup.SessionSetup.create_ai_session_manager')
    @patch('a2a_server.session_store_factory._filter_session_config')
    def test_create_ai_session_manager(self, mock_filter, mock_create_manager):
        """Test creating AI session manager with filtering."""
        mock_manager = Mock()
        mock_create_manager.return_value = mock_manager
        mock_filter.return_value = {'filtered': 'config'}

        session_config = {'sandbox_id': 'test', 'invalid_param': 'value'}
        result = create_ai_session_manager(session_config, 'test-context')

        mock_filter.assert_called_once_with(session_config)
        mock_create_manager.assert_called_once_with({'filtered': 'config'})
        assert result is mock_manager

    @patch('a2a_server.session_store_factory.create_ai_session_manager')
    def test_create_shared_ai_session_manager(self, mock_create):
        """Test creating shared AI session manager."""
        mock_manager = Mock()
        mock_create.return_value = mock_manager

        session_config = {'enable_sessions': True}
        result = create_shared_ai_session_manager(
            'test-sandbox', 'test-session', session_config
        )

        mock_create.assert_called_once_with(
            session_config=session_config,
            session_context='shared:test-sandbox/test-session'
        )
        assert result is mock_manager

    @patch('a2a_server.session_store_factory.create_ai_session_manager')
    def test_create_isolated_ai_session_manager(self, mock_create):
        """Test creating isolated AI session manager."""
        mock_manager = Mock()
        mock_create.return_value = mock_manager

        session_config = {'enable_sessions': True}
        result = create_isolated_ai_session_manager(
            'test-sandbox', 'test-session', session_config
        )

        mock_create.assert_called_once_with(
            session_config=session_config,
            session_context='isolated:test-sandbox:test-session'
        )
        assert result is mock_manager


class TestSessionProvider:
    """Test session provider access."""

    @patch('a2a_server.session_store_factory.get_session_factory')
    def test_get_session_provider(self, mock_get_factory):
        """Test getting session provider from factory."""
        mock_factory = Mock()
        mock_provider = Mock()
        mock_factory.return_value = mock_provider
        mock_get_factory.return_value = mock_factory

        provider = get_session_provider()

        mock_get_factory.assert_called_once()
        mock_factory.assert_called_once()
        assert provider is mock_provider


class TestSessionStats:
    """Test session statistics gathering."""

    def setup_method(self):
        reset_session_caches()

    def teardown_method(self):
        reset_session_caches()

    @patch.dict(os.environ, {'SESSION_PROVIDER': 'redis'})
    def test_get_session_stats_basic(self):
        """Test basic session statistics."""
        stats = get_session_stats()

        expected_keys = {
            'session_managers', 'sandboxes', 'session_provider',
            'ai_session_caching', 'session_sharing'
        }
        assert all(key in stats for key in expected_keys)
        assert stats['session_provider'] == 'redis'
        assert stats['ai_session_caching'] == 'disabled_for_cross_server_compatibility'
        assert stats['session_sharing'] == 'handled_by_external_storage'

    @patch('a2a_server.session_store_factory.SessionManager')
    def test_get_session_stats_with_managers(self, mock_session_manager):
        """Test session statistics with active managers."""
        # Create some session managers
        mock_manager1 = Mock()
        mock_manager1.get_cache_stats.return_value = {'hits': 10, 'misses': 2}
        mock_manager2 = Mock()
        mock_manager2.get_cache_stats.side_effect = AttributeError("Not available")

        mock_session_manager.side_effect = [mock_manager1, mock_manager2]

        # Build some managers to populate cache
        build_session_manager(sandbox_id='sandbox1')
        build_session_manager(sandbox_id='sandbox2')

        stats = get_session_stats()

        assert stats['session_managers'] == 2
        assert set(stats['sandboxes']) == {'sandbox1', 'sandbox2'}
        assert stats['cache_stats_sandbox1'] == {'hits': 10, 'misses': 2}
        assert stats['cache_stats_sandbox2'] == {'available': False}

    @patch('a2a_server.session_store_factory.SessionManager')
    def test_get_session_stats_with_manager_error(self, mock_session_manager):
        """Test session statistics when manager throws unexpected error."""
        mock_manager = Mock()
        mock_manager.get_cache_stats.side_effect = RuntimeError("Connection failed")
        mock_session_manager.return_value = mock_manager

        build_session_manager(sandbox_id='error-sandbox')

        with patch('a2a_server.session_store_factory.logger') as mock_logger:
            stats = get_session_stats()

            mock_logger.warning.assert_called_once()
            assert 'cache_stats_error-sandbox' not in stats


class TestValidateSessionSetup:
    """Test session setup validation."""

    def setup_method(self):
        reset_session_caches()

    @patch('a2a_server.session_store_factory.get_session_factory')
    @patch('a2a_server.session_store_factory.create_ai_session_manager')
    @patch('a2a_server.utils.session_setup.SessionSetup.create_session_config')
    def test_validate_session_setup_success(self, mock_create_config, mock_create_ai, mock_get_factory):
        """Test successful session setup validation."""
        mock_factory = Mock()
        mock_get_factory.return_value = mock_factory
        mock_create_config.return_value = {'test': 'config'}
        mock_ai_manager = Mock()
        mock_create_ai.return_value = mock_ai_manager

        validation = validate_session_setup()

        assert validation['factory_available'] is True
        assert validation['ai_session_creation'] is True
        assert validation['external_storage_only'] is True
        assert validation['cross_server_compatible'] is True

    @patch('a2a_server.session_store_factory.get_session_factory')
    def test_validate_session_setup_factory_error(self, mock_get_factory):
        """Test validation when factory creation fails."""
        mock_get_factory.side_effect = RuntimeError("Factory error")

        validation = validate_session_setup()

        assert validation['factory_available'] is False
        assert validation['factory_error'] == "Factory error"

    @patch('a2a_server.session_store_factory.get_session_factory')
    @patch('a2a_server.session_store_factory.create_ai_session_manager')
    @patch('a2a_server.utils.session_setup.SessionSetup.create_session_config')
    def test_validate_session_setup_ai_error(self, mock_create_config, mock_create_ai, mock_get_factory):
        """Test validation when AI session manager creation fails."""
        mock_factory = Mock()
        mock_get_factory.return_value = mock_factory
        mock_create_config.return_value = {'test': 'config'}
        mock_create_ai.side_effect = ImportError("AI manager not available")

        validation = validate_session_setup()

        assert validation['factory_available'] is True
        assert validation['ai_session_creation'] is False
        assert validation['ai_session_error'] == "AI manager not available"


class TestIntegration:
    """Integration tests combining multiple components."""

    def setup_method(self):
        reset_session_caches()

    def teardown_method(self):
        reset_session_caches()

    @patch('a2a_server.session_store_factory.SessionManager')
    @patch('a2a_server.utils.session_setup.SessionSetup.create_ai_session_manager')
    @patch('a2a_server.utils.session_setup.SessionSetup.create_session_config')
    def test_full_workflow(self, mock_create_config, mock_create_ai, mock_session_manager):
        """Test complete workflow from setup to AI session creation."""
        # Setup mocks
        mock_manager = Mock()
        mock_session_manager.return_value = mock_manager
        mock_create_config.return_value = {
            'sandbox_id': 'test-sandbox',
            'enable_sessions': True,
            'circuit_breaker_threshold': 10  # This should be filtered out
        }
        mock_ai_manager = Mock()
        mock_create_ai.return_value = mock_ai_manager

        # 1. Build session manager
        session_manager = build_session_manager(sandbox_id='test-sandbox')
        assert session_manager is mock_manager

        # 2. Create AI session manager with filtering
        session_config = mock_create_config.return_value
        ai_manager = create_ai_session_manager(session_config, 'test-context')
        assert ai_manager is mock_ai_manager

        # 3. Verify filtering occurred
        mock_create_ai.assert_called_once()
        call_args = mock_create_ai.call_args[0][0]  # First positional argument
        assert 'circuit_breaker_threshold' not in call_args
        assert call_args['enable_sessions'] is True

        # 4. Check stats
        stats = get_session_stats()
        assert stats['session_managers'] == 1
        assert 'test-sandbox' in stats['sandboxes']

    @patch.dict(os.environ, {'SESSION_PROVIDER': 'memory'})
    @patch('a2a_server.session_store_factory.factory_for_env')
    def test_environment_configuration(self, mock_factory_for_env):
        """Test that environment variables are properly used."""
        mock_factory = Mock()
        mock_factory_for_env.return_value = mock_factory

        # Get factory should use environment configuration
        factory = get_session_factory()
        
        mock_factory_for_env.assert_called_once()
        stats = get_session_stats()
        assert stats['session_provider'] == 'memory'


# Test fixtures and utilities
@pytest.fixture
def sample_session_config():
    """Fixture providing a sample session configuration."""
    return {
        'sandbox_id': 'test-sandbox',
        'session_sharing': True,
        'enable_sessions': True,
        'streaming': False,
        'token_threshold': 1000,
        'circuit_breaker_threshold': 10,  # Should be filtered out
        'invalid_param': 'should_be_removed'
    }


@pytest.fixture
def mock_session_setup():
    """Fixture providing mocked SessionSetup."""
    with patch('a2a_server.utils.session_setup.SessionSetup') as mock_setup:
        mock_setup.create_session_config.return_value = {
            'sandbox_id': 'test',
            'enable_sessions': True
        }
        mock_setup.create_ai_session_manager.return_value = Mock()
        mock_setup.setup_ai_storage.return_value = 'final-sandbox'
        yield mock_setup


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_filter_session_config_with_none_values(self):
        """Test filtering configuration with None values."""
        config = {
            'sandbox_id': None,
            'session_sharing': True,
            'invalid_param': None
        }
        
        filtered = _filter_session_config(config)
        expected = {
            'sandbox_id': None,
            'session_sharing': True
        }
        assert filtered == expected

    @patch('a2a_server.session_store_factory.SessionManager')
    def test_build_session_manager_with_empty_sandbox_id(self, mock_session_manager):
        """Test building session manager with empty sandbox ID."""
        with patch('a2a_server.session_store_factory.server_sandbox') as mock_server_sandbox:
            mock_server_sandbox.return_value = 'generated-sandbox'
            mock_manager = Mock()
            mock_session_manager.return_value = mock_manager

            # None should trigger auto-generation (empty string is treated as None in the actual code)
            manager = build_session_manager(sandbox_id=None)
            
            mock_server_sandbox.assert_called_once()
            mock_session_manager.assert_called_once_with(
                sandbox_id='generated-sandbox',
                default_ttl_hours=24
            )

    @patch('a2a_server.session_store_factory.SessionManager')
    def test_build_session_manager_with_none_sandbox_id(self, mock_session_manager):
        """Test building session manager with None sandbox ID triggers auto-generation."""
        with patch('a2a_server.session_store_factory.server_sandbox') as mock_server_sandbox:
            mock_server_sandbox.return_value = 'auto-generated'
            mock_manager = Mock()
            mock_session_manager.return_value = mock_manager

            # Explicitly test None case
            manager = build_session_manager(sandbox_id=None)
            
            mock_server_sandbox.assert_called_once()
            assert manager is mock_manager


if __name__ == '__main__':
    # Run tests with pytest
    pytest.main([__file__, '-v'])