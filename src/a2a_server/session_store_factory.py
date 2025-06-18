#!/usr/bin/env python3
# a2a_server/session_store_factory.py
"""
Modern session store factory using chuk_sessions and chuk_ai_session_manager.

Environment variables
---------------------
SESSION_PROVIDER      "memory" (default) | "redis"
SESSION_REDIS_URL     Redis DSN if the backend is *redis*
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Any

from chuk_sessions.provider_factory import factory_for_env
from chuk_sessions.session_manager import SessionManager
from chuk_ai_session_manager import SessionManager as AISessionManager
from chuk_ai_session_manager.session_storage import setup_chuk_sessions_storage

from a2a_server.utils.session_sandbox import server_sandbox, ai_sandbox

logger = logging.getLogger(__name__)

# Module-level caches
_session_managers: Dict[str, SessionManager] = {}
_ai_session_managers: Dict[str, AISessionManager] = {}
_session_factory = None


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


def build_ai_session_manager(
    session_id: str = "default",
    *,
    infinite_context: bool = True,
    token_threshold: int = 4000,
    max_turns_per_segment: int = 50,
    refresh: bool = False,
    **kwargs
) -> AISessionManager:
    """
    Build or return cached AI SessionManager.
    
    Args:
        session_id: Unique identifier for this AI session manager
        infinite_context: Enable infinite context with segmentation
        token_threshold: Token limit before segmentation
        max_turns_per_segment: Maximum turns per segment
        refresh: Force creation of new manager
        **kwargs: Additional arguments for AISessionManager
        
    Returns:
        AISessionManager instance
    """
    global _ai_session_managers
    
    cache_key = f"{session_id}:{infinite_context}:{token_threshold}:{max_turns_per_segment}"
    
    if cache_key in _ai_session_managers and not refresh:
        return _ai_session_managers[cache_key]
    
    from a2a_server.utils.session_setup import SessionSetup
    
    session_config = SessionSetup.create_session_config(
        infinite_context=infinite_context,
        token_threshold=token_threshold,
        max_turns_per_segment=max_turns_per_segment,
        **kwargs
    )
    
    manager = SessionSetup.create_ai_session_manager(session_config)
    
    _ai_session_managers[cache_key] = manager
    logger.info(
        "Created AI SessionManager '%s' (infinite=%s, threshold=%d)",
        session_id, infinite_context, token_threshold
    )
    
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
    
    Returns:
        Dictionary with session statistics
    """
    stats = {
        "session_managers": len(_session_managers),
        "ai_session_managers": len(_ai_session_managers),
        "sandboxes": list(_session_managers.keys()),
        "session_provider": os.getenv("SESSION_PROVIDER", "memory")
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
    """Reset all cached session managers (useful for testing)."""
    global _session_managers, _ai_session_managers, _session_factory
    
    _session_managers.clear()
    _ai_session_managers.clear()
    _session_factory = None
    
    logger.info("Reset all session manager caches")


__all__ = [
    "build_session_manager",
    "build_session_store",
    "setup_ai_session_storage", 
    "build_ai_session_manager",
    "get_session_factory",
    "get_session_provider",
    "get_session_stats",
    "reset_session_caches"
]