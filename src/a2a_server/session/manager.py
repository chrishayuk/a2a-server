#!/usr/bin/env python3
# a2a_server/session/manager.py
"""
Provides a unified interface for initializing session components WITHOUT
the SessionLifecycleManager that was causing duplicate task creation.
Sessions now rely on natural auto-expiration through TTL.
"""
import logging
import importlib
from typing import Dict, Optional, Any, Tuple
from fastapi import FastAPI

# logger
logger = logging.getLogger(__name__)

# Known session store providers
STORE_PROVIDERS = {
    "memory": "chuk_session_manager.storage.providers.memory.InMemorySessionStore"
}

def initialize_session_components(
    app: FastAPI,
    task_manager: Any,
    session_config: Dict[str, Any]
) -> Tuple[Optional[Any], Optional[Any]]:
    """
    Initialize session components based on configuration.
    
    CLEANED VERSION: No SessionLifecycleManager to prevent duplicate task creation.
    Sessions now rely on natural TTL-based expiration.
    
    Args:
        app: The FastAPI application
        task_manager: The A2A task manager
        session_config: Session configuration dictionary
        
    Returns:
        Tuple of (session_store, None) - lifecycle_manager removed
    """
    # Check if sessions are enabled
    if not session_config.get("enabled", False):
        return None, None
    
    try:
        # Initialize session store
        store_type = session_config.get("store_type", "memory")
        store = _create_session_store(store_type, session_config)
        
        if store is None:
            logger.warning("Failed to create session store")
            return None, None
        
        logger.info("Initialized %s session store with TTL-based auto-expiration", store_type)    
        logger.info("Session lifecycle: Using TTL-based auto-expiration (no manual cleanup)")
        
        # Set store in app state
        app.state.session_store = store
        # NOTE: No session_lifecycle_manager in app state
        
        # Register session API routes
        _register_session_routes(app)
        
        return store, None  # Return None instead of lifecycle_manager
        
    except Exception as e:
        logger.exception("Error initializing session components: %s", e)
        return None, None


def _create_session_store(store_type: str, config: Dict[str, Any]) -> Optional[Any]:
    """
    Create a session store instance based on configuration.
    
    Args:
        store_type: Type of store ('memory', 'redis', etc.)
        config: Session configuration dictionary
        
    Returns:
        Session store instance or None if creation failed
    """
    if store_type not in STORE_PROVIDERS:
        logger.warning("Unknown session store type: %s, defaulting to memory", store_type)
        store_type = "memory"
    
    store_class_path = STORE_PROVIDERS[store_type]
    
    try:
        # Import the store class
        module_path, class_name = store_class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        store_class = getattr(module, class_name)
        
        # Create store instance with appropriate parameters
        if store_type == "memory":
            store = store_class()
        elif store_type == "redis":
            # Get Redis-specific configuration
            redis_config = config.get("redis", {})
            store = store_class(
                redis_url=redis_config.get("url", "redis://localhost:6379/0"),
                prefix=redis_config.get("prefix", "a2a:session:"),
                ttl=redis_config.get("ttl", 86400 * 7)  # 7 days default
            )
        else:
            # Generic initialization
            store = store_class()
        
        # Set the store in the provider
        from chuk_session_manager.storage import SessionStoreProvider
        SessionStoreProvider.set_store(store)
        
        return store
    except Exception as e:
        logger.exception("Error creating session store: %s", e)
        return None


def _register_session_routes(app: FastAPI) -> None:
    """
    Register all session-related API routes.
    
    Args:
        app: The FastAPI application
    """
    try:
        # Register base session routes
        from a2a_server.routes.session_routes import register_session_routes
        register_session_routes(app)
        logger.info("Registered session routes")
        
        # Register analytics routes
        try:
            from a2a_server.routes.session_analytics import register_session_analytics_routes
            register_session_analytics_routes(app)
            logger.info("Registered session analytics routes")
        except ImportError as e:
            logger.warning("Session analytics module not available: %s", e)
        
        # Register export/import routes
        try:
            from a2a_server.routes.session_export import register_session_export_routes
            register_session_export_routes(app)
            logger.info("Registered session export/import routes")
        except ImportError as e:
            logger.warning("Session export module not available: %s", e)
            
    except ImportError as e:
        logger.warning("Session routes module not available: %s", e)


def setup_session_lifecycle_events(app: FastAPI) -> None:
    """
    Set up FastAPI startup/shutdown events for session management.
    
    CLEANED VERSION: No lifecycle manager startup/shutdown since we removed it.
    
    Args:
        app: The FastAPI application
    """
    logger.info("Session lifecycle events: Using TTL-based expiration (no manual lifecycle)")
    
    @app.on_event("shutdown")
    async def cleanup_session_store():
        """Clean shutdown of session store if needed."""
        if hasattr(app.state, "session_store") and hasattr(app.state.session_store, "disconnect"):
            await app.state.session_store.disconnect()
            logger.info("Session store disconnected cleanly")
    
    # NOTE: No startup event for SessionLifecycleManager since we removed it
    # Sessions now handle their own lifecycle through TTL expiration