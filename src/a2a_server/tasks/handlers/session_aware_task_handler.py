# File: a2a_server/tasks/handlers/session_aware_task_handler.py
from __future__ import annotations
import logging
from typing import Dict, List, Optional, Any

from chuk_ai_session_manager import SessionManager as AISessionManager

from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_server.utils.session_setup import SessionSetup, setup_handler_sessions

logger = logging.getLogger(__name__)


class SessionAwareTaskHandler(TaskHandler):
    """Base class for task handlers that support session management."""

    def __init__(
        self,
        name: str,
        sandbox_id: Optional[str] = None,
        infinite_context: bool = True,
        token_threshold: int = 4000,
        max_turns_per_segment: int = 50,
        default_ttl_hours: int = 24,
        session_store=None,  # Accept session_store from discovery
        **ai_session_kwargs
    ) -> None:
        self._name = name
        
        # Use common session setup utility
        self.sandbox_id, self.session_config = setup_handler_sessions(
            handler_name=name,
            sandbox_id=sandbox_id,
            default_ttl_hours=default_ttl_hours,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            **ai_session_kwargs
        )
        
        # Map A2A session IDs to AI session managers
        self._ai_session_managers: Dict[str, AISessionManager] = {}
        
        logger.info("Session support enabled for handler '%s' (sandbox: %s)", name, self.sandbox_id)

    @property
    def name(self) -> str:
        """Return the registered name of this handler."""
        return self._name

    async def _get_ai_session_manager(self, a2a_session_id: Optional[str]) -> AISessionManager:
        """Get or create AI session manager for an A2A session."""
        if not a2a_session_id:
            # Create ephemeral session manager for one-off requests
            return SessionSetup.create_ai_session_manager(self.session_config)
        
        if a2a_session_id not in self._ai_session_managers:
            self._ai_session_managers[a2a_session_id] = SessionSetup.create_ai_session_manager(self.session_config)
        
        return self._ai_session_managers[a2a_session_id]

    async def add_user_message(self, session_id: Optional[str], message: str) -> bool:
        """Add user message to conversation tracking."""
        try:
            ai_session = await self._get_ai_session_manager(session_id)
            await ai_session.user_says(message)
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
        """Add AI response to conversation tracking."""
        try:
            ai_session = await self._get_ai_session_manager(session_id)
            await ai_session.ai_responds(response, model=model, provider=provider)
            return True
        except Exception:
            logger.exception("Failed to add AI response to session %s", session_id)
            return False

    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Get full conversation history for a session."""
        if not session_id or session_id not in self._ai_session_managers:
            return []

        try:
            ai_session = self._ai_session_managers[session_id]
            conversation = await ai_session.get_conversation()
            return conversation
        except Exception:
            logger.exception("Failed to get conversation history for %s", session_id)
            return []

    async def get_conversation_context(
        self, 
        session_id: Optional[str] = None,
        max_messages: int = 10
    ) -> List[Dict[str, str]]:
        """Get recent conversation context for LLM calls."""
        history = await self.get_conversation_history(session_id)
        return history[-max_messages:] if history else []

    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage statistics for a session."""
        if not session_id or session_id not in self._ai_session_managers:
            return SessionSetup.get_default_token_usage_stats()

        ai_session = self._ai_session_managers[session_id]
        return SessionSetup.extract_session_stats(ai_session)

    async def get_session_chain(self, session_id: Optional[str] = None) -> List[str]:
        """Get the session chain (for infinite context segmentation)."""
        if not session_id or session_id not in self._ai_session_managers:
            return []

        try:
            ai_session = self._ai_session_managers[session_id]
            chain = await ai_session.get_session_chain()
            return chain
        except Exception:
            logger.exception("Failed to get session chain for %s", session_id)
            return []

    async def cleanup_session(self, session_id: str) -> bool:
        """Clean up session resources."""
        if session_id in self._ai_session_managers:
            try:
                # The AI session manager handles its own cleanup via TTL
                del self._ai_session_managers[session_id]
                return True
            except Exception:
                logger.exception("Error cleaning up session %s", session_id)
                return False
        return True

    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about this handler's sessions."""
        return {
            "handler_name": self.name,
            "sandbox_id": self.sandbox_id,
            "active_sessions": len(self._ai_session_managers),
            "session_ids": list(self._ai_session_managers.keys()),
            "session_config": self.session_config
        }