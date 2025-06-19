# File: a2a_server/tasks/handlers/session_aware_task_handler.py
from __future__ import annotations
import logging
from typing import Dict, List, Optional, Any

from chuk_ai_session_manager import SessionManager as AISessionManager

from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_server.utils.session_setup import SessionSetup, setup_handler_sessions
from a2a_server.session_store_factory import (
    create_shared_ai_session_manager,
    create_isolated_ai_session_manager,
    validate_session_setup
)

logger = logging.getLogger(__name__)


class SessionAwareTaskHandler(TaskHandler):
    """
    Base class for task handlers that support session management with proper external storage.
    
    This implementation relies entirely on external CHUK session storage for cross-server
    and cross-agent session sharing. No in-memory session caching is used.
    """

    def __init__(
        self,
        name: str,
        sandbox_id: Optional[str] = None,
        infinite_context: bool = True,
        token_threshold: int = 4000,
        max_turns_per_segment: int = 50,
        default_ttl_hours: int = 24,
        session_store=None,
        # Session sharing configuration
        session_sharing: Optional[bool] = None,  # None = auto-detect, True = enable, False = disable
        shared_sandbox_group: Optional[str] = None,  # Override sandbox for sharing purposes
        **ai_session_kwargs
    ) -> None:
        self._name = name
        
        # Determine session sharing strategy
        self.session_sharing = self._determine_session_sharing(session_sharing, shared_sandbox_group)
        
        # Use shared sandbox group if session sharing is enabled, otherwise use handler-specific sandbox
        effective_sandbox = shared_sandbox_group if self.session_sharing else sandbox_id
        
        # Use common session setup utility
        self.sandbox_id, self.session_config = setup_handler_sessions(
            handler_name=name,
            sandbox_id=effective_sandbox,
            default_ttl_hours=default_ttl_hours,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            **ai_session_kwargs
        )
        
        # Store shared sandbox group for cross-agent sharing
        self.shared_sandbox_group = shared_sandbox_group or self.sandbox_id
        
        if self.session_sharing:
            logger.info("Session support enabled for handler '%s' with SHARED external sessions (group: %s)", 
                       name, self.shared_sandbox_group)
        else:
            logger.info("Session support enabled for handler '%s' with ISOLATED external sessions (sandbox: %s)", 
                       name, self.sandbox_id)

    def _determine_session_sharing(self, session_sharing: Optional[bool], shared_sandbox_group: Optional[str]) -> bool:
        """
        Determine whether to enable session sharing based on configuration.
        
        Args:
            session_sharing: Explicit session sharing setting
            shared_sandbox_group: Shared sandbox group override
            
        Returns:
            True if session sharing should be enabled
        """
        # Explicit configuration takes precedence
        if session_sharing is not None:
            return session_sharing
        
        # If shared_sandbox_group is specified, enable sharing
        if shared_sandbox_group is not None:
            return True
        
        # Default: no sharing (safer default)
        return False

    @property
    def name(self) -> str:
        """Return the registered name of this handler."""
        return self._name

    async def _get_ai_session_manager(self, a2a_session_id: Optional[str]) -> AISessionManager:
        """
        Get AI session manager that connects to external storage.
        
        IMPORTANT: This creates a NEW manager instance each time that connects to
        the external storage. This ensures proper cross-server session sharing.
        """
        if not a2a_session_id:
            # Create ephemeral session manager for one-off requests
            return SessionSetup.create_ai_session_manager(self.session_config)
        
        if self.session_sharing:
            # Create shared AI session manager - connects to shared external storage
            return create_shared_ai_session_manager(
                sandbox_id=self.shared_sandbox_group,
                session_id=a2a_session_id,
                session_config=self.session_config
            )
        else:
            # Create isolated session manager - connects to isolated external storage
            return create_isolated_ai_session_manager(
                sandbox_id=self.sandbox_id,
                session_id=a2a_session_id,
                session_config=self.session_config
            )

    async def add_user_message(self, session_id: Optional[str], message: str) -> bool:
        """Add user message to external session storage."""
        try:
            ai_session = await self._get_ai_session_manager(session_id)
            await ai_session.user_says(message)
            
            log_prefix = "📝🌐" if self.session_sharing else "📝🔒"
            logger.debug(f"{log_prefix} Added user message to external session {session_id}")
            return True
        except Exception:
            logger.exception("Failed to add user message to session %s", session_id)
            return False

    async def add_ai_response(
        self, 
        session_id: Optional[str], 
        response: str,
        model: str = "unknown",
        provider: str = "unknown"
    ) -> bool:
        """Add AI response to external session storage."""
        try:
            ai_session = await self._get_ai_session_manager(session_id)
            await ai_session.ai_responds(response, model=model, provider=provider)
            
            log_prefix = "📝🌐" if self.session_sharing else "📝🔒"
            logger.debug(f"{log_prefix} Added AI response to external session {session_id}")
            return True
        except Exception:
            logger.exception("Failed to add AI response to session %s", session_id)
            return False

    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Get full conversation history from external session storage."""
        if not session_id:
            return []

        try:
            ai_session = await self._get_ai_session_manager(session_id)
            conversation = await ai_session.get_conversation()
            
            log_prefix = "🔍🌐" if self.session_sharing else "🔍🔒"
            logger.debug(f"{log_prefix} Retrieved {len(conversation)} messages from external session {session_id}")
            return conversation
        except Exception:
            logger.exception("Failed to get conversation history for %s", session_id)
            return []

    async def get_conversation_context(
        self, 
        session_id: Optional[str] = None,
        max_messages: int = 10
    ) -> List[Dict[str, str]]:
        """Get recent conversation context from external session storage."""
        history = await self.get_conversation_history(session_id)
        context = history[-max_messages:] if history else []
        
        log_prefix = "🔍🌐" if self.session_sharing else "🔍🔒"
        logger.debug(f"{log_prefix} Returning {len(context)} context messages from external storage for {self._name}")
        return context

    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage statistics from external session storage."""
        if not session_id:
            return SessionSetup.get_default_token_usage_stats()

        try:
            ai_session = await self._get_ai_session_manager(session_id)
            return SessionSetup.extract_session_stats(ai_session)
        except Exception:
            return SessionSetup.get_default_token_usage_stats()

    async def get_session_chain(self, session_id: Optional[str] = None) -> List[str]:
        """Get the session chain from external session storage."""
        if not session_id:
            return []

        try:
            ai_session = await self._get_ai_session_manager(session_id)
            chain = await ai_session.get_session_chain()
            return chain
        except Exception:
            logger.exception("Failed to get session chain for %s", session_id)
            return []

    async def cleanup_session(self, session_id: str) -> bool:
        """
        Clean up session resources from external storage.
        
        Note: External sessions are typically cleaned up via TTL in the storage system.
        This method is mainly for compatibility and logging.
        """
        storage_type = "shared" if self.session_sharing else "isolated"
        sandbox = self.shared_sandbox_group if self.session_sharing else self.sandbox_id
        
        logger.info(f"🗑️ Session cleanup requested for {storage_type} external session: {sandbox}/{session_id}")
        
        # External sessions are cleaned up via TTL, not manual cleanup
        # The external storage system handles this automatically
        return True

    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about this handler's session configuration."""
        return {
            "handler_name": self.name,
            "sandbox_id": self.sandbox_id,
            "shared_sandbox_group": self.shared_sandbox_group,
            "session_sharing": "enabled" if self.session_sharing else "disabled",
            "session_storage": "external_chuk_sessions_only",
            "cross_server_compatible": True,
            "session_caching": "disabled_for_cross_server_compatibility",
            "session_config": self.session_config
        }

    def validate_session_configuration(self) -> Dict[str, Any]:
        """
        Validate this handler's session configuration.
        
        Returns:
            Validation results
        """
        validation = {
            "handler_name": self.name,
            "configuration_valid": True,
            "issues": []
        }
        
        # Check if session sharing configuration makes sense
        if self.session_sharing and not self.shared_sandbox_group:
            validation["configuration_valid"] = False
            validation["issues"].append("Session sharing enabled but no shared_sandbox_group specified")
        
        if not self.session_sharing and self.shared_sandbox_group:
            validation["issues"].append("shared_sandbox_group specified but session sharing disabled")
        
        # Validate session setup
        try:
            session_validation = validate_session_setup()
            validation["session_setup"] = session_validation
        except Exception as e:
            validation["configuration_valid"] = False
            validation["issues"].append(f"Session setup validation failed: {e}")
        
        return validation