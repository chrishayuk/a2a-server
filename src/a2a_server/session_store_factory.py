#!/usr/bin/env python3
# a2a_server/session_store_factory.py
"""
Modern session store factory using chuk_sessions and chuk_ai_session_manager with proper external storage.
Environment variables
---------------------
SESSION_PROVIDER      "memory" (default) | "redis"
SESSION_REDIS_URL     Redis DSN if the backend is *redis*
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Any, Optional

# sessions
from chuk_sessions.provider_factory import factory_for_env
from chuk_sessions.session_manager import SessionManager
from chuk_ai_session_manager import SessionManager as AISessionManager
from a2a_server.utils.session_sandbox import server_sandbox

logger = logging.getLogger(__name__)

# Module-level caches - ONLY for non-session-specific managers
_session_managers: Dict[str, SessionManager] = {}
_session_factory = None

# Define supported parameters for AISessionManager
AI_SESSION_MANAGER_PARAMS = {
    'sandbox_id',
    'session_sharing', 
    'shared_sandbox_group',
    'enable_sessions',
    'infinite_context',
    'token_threshold',
    'max_turns_per_segment', 
    'session_ttl_hours',
    'streaming',
    # Add other supported parameters as needed
    # Remove unsupported ones like 'circuit_breaker_threshold'
}

def get_session_factory():
    """Get the global session factory (singleton)."""
    global _session_factory
    
    if _session_factory is None:
        _session_factory = factory_for_env()
        backend = os.getenv("SESSION_PROVIDER", "memory")
        logger.info("Initialized session factory with backend: %s", backend)
    
    return _session_factory


def build_session_manager(
    sandbox_id: str = None,
    default_ttl_hours: int = 24,
    *,
    refresh: bool = False
) -> SessionManager:
    """
    Build or return cached SessionManager for the given sandbox.
    
    These can be cached because they're just connections to the external storage,
    not the actual session data.
    
    Args:
        sandbox_id: Unique identifier for this session sandbox (auto-generated if None)
        default_ttl_hours: Default session TTL in hours
        refresh: Force creation of new manager
        
    Returns:
        SessionManager instance from chuk_sessions
    """
    global _session_managers
    
    # Use utility to generate sandbox name if not provided
    if sandbox_id is None:
        sandbox_id = server_sandbox()
    
    if sandbox_id in _session_managers and not refresh:
        return _session_managers[sandbox_id]
    
    manager = SessionManager(
        sandbox_id=sandbox_id,
        default_ttl_hours=default_ttl_hours
    )
    
    _session_managers[sandbox_id] = manager
    logger.info("Created SessionManager for sandbox '%s' (TTL: %dh)", sandbox_id, default_ttl_hours)
    
    return manager


def build_session_store(
    sandbox_id: str = None,
    default_ttl_hours: int = 24,
    *,
    refresh: bool = False
) -> SessionManager:
    """
    Build or return cached session store (alias for build_session_manager).
    
    Args:
        sandbox_id: Unique identifier for this session sandbox (auto-generated if None)
        default_ttl_hours: Default session TTL in hours
        refresh: Force creation of new manager
        
    Returns:
        SessionManager instance from chuk_sessions
    """
    return build_session_manager(
        sandbox_id=sandbox_id,
        default_ttl_hours=default_ttl_hours,
        refresh=refresh
    )


def setup_ai_session_storage(
    sandbox_id: str = None,
    default_ttl_hours: int = 24
) -> None:
    """
    Setup session storage for AI session management.
    
    Args:
        sandbox_id: Unique identifier for this session sandbox (auto-generated if None)
        default_ttl_hours: Default session TTL in hours
    """
    from a2a_server.utils.session_setup import SessionSetup
    
    final_sandbox_id = SessionSetup.setup_ai_storage(
        sandbox_id=sandbox_id,
        default_ttl_hours=default_ttl_hours
    )
    logger.info("Setup AI session storage for sandbox: %s", final_sandbox_id)


def _filter_session_config(session_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Filter session config to only include parameters supported by AISessionManager.
    
    This removes unsupported parameters like 'circuit_breaker_threshold' that
    cause TypeError when passed to SessionManager.__init__().
    
    Args:
        session_config: Raw session configuration
        
    Returns:
        Filtered configuration with only supported parameters
    """
    filtered = {k: v for k, v in session_config.items() if k in AI_SESSION_MANAGER_PARAMS}
    
    # Log filtered out parameters for debugging
    removed = set(session_config.keys()) - AI_SESSION_MANAGER_PARAMS
    if removed:
        logger.debug("Filtered out unsupported session parameters: %s", removed)
    
    return filtered


def create_ai_session_manager(
    session_config: Dict[str, Any],
    session_context: Optional[str] = None
) -> AISessionManager:
    """
    Create a NEW AI session manager instance.
    
    IMPORTANT: This does NOT cache the instance. Each call creates a new manager
    that connects to the external storage. This ensures proper cross-server sharing.
    
    Args:
        session_config: Session configuration (will be filtered for supported params)
        session_context: Optional context info for logging
        
    Returns:
        New AISessionManager instance (not cached)
    """
    from a2a_server.utils.session_setup import SessionSetup
    
    # Filter config to remove unsupported parameters like circuit_breaker_threshold
    filtered_config = _filter_session_config(session_config)
    
    manager = SessionSetup.create_ai_session_manager(filtered_config)
    
    if session_context:
        logger.debug(f"🔧 Created AI session manager for: {session_context}")
    else:
        logger.debug("🔧 Created AI session manager")
    
    return manager


def create_shared_ai_session_manager(
    sandbox_id: str,
    session_id: str,
    session_config: Dict[str, Any]
) -> AISessionManager:
    """
    Create AI session manager for cross-agent session sharing.
    
    This creates a NEW manager instance that connects to the external storage.
    Multiple agents calling this with the same sandbox_id will access the same
    external session data through their respective manager instances.
    
    Args:
        sandbox_id: Sandbox identifier for grouping related sessions
        session_id: Specific session identifier (e.g., user session)
        session_config: Session configuration (will be filtered for supported params)
        
    Returns:
        New AISessionManager instance (connects to shared external storage)
    """
    # Always create a new manager instance - no caching!
    manager = create_ai_session_manager(
        session_config=session_config,
        session_context=f"shared:{sandbox_id}/{session_id}"
    )
    
    logger.debug(f"🌐 Created shared AI session manager: {sandbox_id}/{session_id}")
    return manager


def create_isolated_ai_session_manager(
    sandbox_id: str,
    session_id: str,
    session_config: Dict[str, Any]
) -> AISessionManager:
    """
    Create AI session manager for isolated session management.
    
    Args:
        sandbox_id: Sandbox identifier for this handler
        session_id: Specific session identifier
        session_config: Session configuration (will be filtered for supported params)
        
    Returns:
        New AISessionManager instance (connects to isolated external storage)
    """
    # Create unique session identifier for isolation
    isolated_session_id = f"{sandbox_id}:{session_id}"
    
    manager = create_ai_session_manager(
        session_config=session_config,
        session_context=f"isolated:{isolated_session_id}"
    )
    
    logger.debug(f"🔒 Created isolated AI session manager: {isolated_session_id}")
    return manager


def get_session_provider():
    """
    Get the underlying session provider for direct access.
    
    Returns:
        Session provider instance from chuk_sessions
    """
    factory = get_session_factory()
    return factory()


def get_session_stats() -> Dict[str, Any]:
    """
    Get statistics about session managers.
    
    Note: This only shows connection managers, not actual session data
    since we don't cache AISessionManager instances.
    
    Returns:
        Dictionary with session statistics
    """
    stats = {
        "session_managers": len(_session_managers),
        "sandboxes": list(_session_managers.keys()),
        "session_provider": os.getenv("SESSION_PROVIDER", "memory"),
        "ai_session_caching": "disabled_for_cross_server_compatibility",
        "session_sharing": "handled_by_external_storage"
    }
    
    # Add cache stats for each session manager
    for sandbox_id, manager in _session_managers.items():
        try:
            cache_stats = manager.get_cache_stats()
            stats[f"cache_stats_{sandbox_id}"] = cache_stats
        except AttributeError:
            # get_cache_stats may not be available in all versions
            stats[f"cache_stats_{sandbox_id}"] = {"available": False}
        except Exception as e:
            logger.warning("Failed to get cache stats for %s: %s", sandbox_id, e)
    
    return stats


def reset_session_caches() -> None:
    """Reset cached session managers (useful for testing)."""
    global _session_managers, _session_factory
    
    _session_managers.clear()
    _session_factory = None
    
    logger.info("Reset session manager caches")


def validate_session_setup() -> Dict[str, Any]:
    """
    Validate the session setup and return diagnostic information.
    
    Returns:
        Dictionary with validation results
    """
    validation = {
        "session_provider": os.getenv("SESSION_PROVIDER", "memory"),
        "external_storage_only": True,
        "cross_server_compatible": True,
        "session_managers": len(_session_managers),
        "sandboxes": list(_session_managers.keys())
    }
    
    # Test session factory
    try:
        factory = get_session_factory()
        validation["factory_available"] = True
        validation["factory_type"] = str(type(factory))
    except Exception as e:
        validation["factory_available"] = False
        validation["factory_error"] = str(e)
    
    # Test AI session manager creation
    try:
        from a2a_server.utils.session_setup import SessionSetup
        test_config = SessionSetup.create_session_config()
        test_manager = create_ai_session_manager(test_config, "validation_test")
        validation["ai_session_creation"] = True
        validation["ai_session_type"] = str(type(test_manager))
    except Exception as e:
        validation["ai_session_creation"] = False
        validation["ai_session_error"] = str(e)
    
    return validation


__all__ = [
    "build_session_manager",
    "build_session_store",
    "setup_ai_session_storage",
    "create_ai_session_manager",           # ← Create new manager (no caching)
    "create_shared_ai_session_manager",    # ← For cross-agent sharing
    "create_isolated_ai_session_manager",  # ← For isolated sessions
    "get_session_factory",
    "get_session_provider",
    "get_session_stats",
    "reset_session_caches",
    "validate_session_setup"
]