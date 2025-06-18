# File: a2a_server/utils/session_setup.py
"""
Common session setup utilities for consistent configuration across handlers and factories.
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from chuk_ai_session_manager import SessionManager as AISessionManager
from chuk_ai_session_manager.session_storage import setup_chuk_sessions_storage

from a2a_server.utils.session_sandbox import handler_sandbox, ai_sandbox

logger = logging.getLogger(__name__)


class SessionSetup:
    """Utility class for consistent session setup across the application."""
    
    @classmethod
    def setup_handler_storage(
        cls,
        handler_name: str,
        sandbox_id: Optional[str] = None,
        default_ttl_hours: int = 24,
        config: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Setup session storage for a task handler.
        
        Args:
            handler_name: Name of the handler
            sandbox_id: Optional explicit sandbox ID
            default_ttl_hours: Default TTL for sessions
            config: Optional configuration dict
            
        Returns:
            The sandbox ID that was used
        """
        # Determine sandbox name
        if sandbox_id:
            final_sandbox_id = sandbox_id
        else:
            final_sandbox_id = handler_sandbox(handler_name, config)
        
        # Setup storage
        setup_chuk_sessions_storage(
            sandbox_id=final_sandbox_id,
            default_ttl_hours=default_ttl_hours
        )
        
        logger.debug("Setup session storage for handler '%s' (sandbox: %s)", 
                    handler_name, final_sandbox_id)
        
        return final_sandbox_id
    
    @classmethod
    def setup_ai_storage(
        cls,
        sandbox_id: Optional[str] = None,
        default_ttl_hours: int = 24,
        session_type: str = "manager"
    ) -> str:
        """
        Setup session storage for AI session management.
        
        Args:
            sandbox_id: Optional explicit sandbox ID
            default_ttl_hours: Default TTL for sessions
            session_type: Type of AI session (for sandbox naming)
            
        Returns:
            The sandbox ID that was used
        """
        # Determine sandbox name
        if sandbox_id:
            final_sandbox_id = sandbox_id
        else:
            final_sandbox_id = ai_sandbox(session_type)
        
        # Setup storage
        setup_chuk_sessions_storage(
            sandbox_id=final_sandbox_id,
            default_ttl_hours=default_ttl_hours
        )
        
        logger.debug("Setup AI session storage (sandbox: %s)", final_sandbox_id)
        
        return final_sandbox_id
    
    @classmethod
    def create_session_config(
        cls,
        infinite_context: bool = True,
        token_threshold: int = 4000,
        max_turns_per_segment: int = 50,
        **additional_kwargs
    ) -> Dict[str, Any]:
        """
        Create standardized session configuration.
        
        Args:
            infinite_context: Enable infinite context with segmentation
            token_threshold: Token limit before segmentation
            max_turns_per_segment: Maximum turns per segment
            **additional_kwargs: Additional session configuration
            
        Returns:
            Session configuration dictionary
        """
        return {
            "infinite_context": infinite_context,
            "token_threshold": token_threshold,
            "max_turns_per_segment": max_turns_per_segment,
            **additional_kwargs
        }
    
    @classmethod
    def create_ai_session_manager(
        cls,
        session_config: Dict[str, Any]
    ) -> AISessionManager:
        """
        Create an AI session manager with the given configuration.
        
        Args:
            session_config: Session configuration dictionary
            
        Returns:
            Configured AISessionManager instance
        """
        return AISessionManager(**session_config)
    
    @classmethod
    def get_default_token_usage_stats(cls) -> Dict[str, Any]:
        """
        Get default token usage statistics for empty sessions.
        
        Returns:
            Default statistics dictionary
        """
        return {
            "total_tokens": 0,
            "estimated_cost": 0,
            "user_messages": 0,
            "ai_messages": 0,
            "session_segments": 0
        }
    
    @classmethod
    def extract_session_stats(
        cls, 
        ai_session: AISessionManager,
        fallback_stats: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Extract statistics from an AI session manager.
        
        Args:
            ai_session: The AI session manager
            fallback_stats: Statistics to return if extraction fails
            
        Returns:
            Session statistics dictionary
        """
        try:
            stats = ai_session.get_stats()
            
            return {
                "total_tokens": stats.get("total_tokens", 0),
                "estimated_cost": stats.get("estimated_cost", 0),
                "user_messages": stats.get("user_messages", 0),
                "ai_messages": stats.get("ai_messages", 0),
                "session_segments": stats.get("session_segments", 1),
                "current_session_id": ai_session.session_id
            }
        except Exception as e:
            logger.warning("Failed to extract session stats: %s", e)
            return fallback_stats or cls.get_default_token_usage_stats()


# Convenience functions for common patterns
def setup_handler_sessions(
    handler_name: str,
    sandbox_id: Optional[str] = None,
    default_ttl_hours: int = 24,
    infinite_context: bool = True,
    token_threshold: int = 4000,
    max_turns_per_segment: int = 50,
    config: Optional[Dict[str, Any]] = None,
    **additional_kwargs
) -> tuple[str, Dict[str, Any]]:
    """
    Complete session setup for a handler.
    
    Returns:
        Tuple of (sandbox_id, session_config)
    """
    sandbox_id = SessionSetup.setup_handler_storage(
        handler_name=handler_name,
        sandbox_id=sandbox_id,
        default_ttl_hours=default_ttl_hours,
        config=config
    )
    
    session_config = SessionSetup.create_session_config(
        infinite_context=infinite_context,
        token_threshold=token_threshold,
        max_turns_per_segment=max_turns_per_segment,
        **additional_kwargs
    )
    
    return sandbox_id, session_config