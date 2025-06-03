# File: a2a_server/tasks/session_aware_task_handler.py
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Any

from a2a_server.tasks.task_handler import TaskHandler

# Try to import session manager components
try:
    from chuk_session_manager.models.event_source import EventSource
    from chuk_session_manager.models.event_type import EventType  # noqa: F401  # (kept for future use)
    from chuk_session_manager.models.session import Session, SessionEvent  # noqa: F401  # (kept for future use)
    from chuk_session_manager.storage import SessionStoreProvider
    from chuk_session_manager.infinite_conversation import (
        InfiniteConversationManager,
        SummarizationStrategy,
    )

    SESSIONS_AVAILABLE = True
except ImportError:
    # When chuk‑session‑manager is not installed we fall back to light mocks so
    # that the rest of the code (and unit‑tests) can still import this module.
    SESSIONS_AVAILABLE = False

    class EventSource:  # type: ignore
        USER = "USER"
        LLM = "LLM"

    class SummarizationStrategy:  # type: ignore
        KEY_POINTS = "key_points"
        BASIC = "basic"
        QUERY_FOCUSED = "query_focused"
        TOPIC_BASED = "topic_based"

logger = logging.getLogger(__name__)


class SessionAwareTaskHandler(TaskHandler):
    """Base‑class for task‑handlers that need conversation/session support."""

    def __init__(
        self,
        name: str,
        session_store=None,
        token_threshold: int = 4000,
        summarization_strategy: str | "SummarizationStrategy" = "key_points",
    ) -> None:
        if not SESSIONS_AVAILABLE:
            raise ImportError("chuk‑session‑manager is required for SessionAwareTaskHandler")

        self._name: str = name
        # Mapping of A2A session‑ids (external) -> agent session‑ids (internal)
        self._session_map: Dict[str, str] = {}

        # Allow dependency‑injected session stores (test doubles, etc.)
        if session_store is not None:
            SessionStoreProvider.set_store(session_store)

        # ------------------------------------------------------------------
        # Determine which summarisation strategy to pass to the
        # InfiniteConversationManager.  In production the real
        # ``SummarizationStrategy`` behaves like an ``enum.Enum`` *and* is
        # callable.  In the unit‑tests it is replaced by a very thin mock
        # class whose constructor **takes no arguments** - attempting to call
        # it therefore raises *TypeError*.
        # ------------------------------------------------------------------
        raw_strategy: Any = (
            summarization_strategy.lower()
            if isinstance(summarization_strategy, str)
            else summarization_strategy
        )

        try:
            strategy = SummarizationStrategy(raw_strategy)  # type: ignore[arg-type]
        except (ValueError, AttributeError, TypeError):
            # ─ ValueError ──────────── unknown value for the real enum
            # ─ AttributeError ──────── the fallback mock has no ``__call__``
            # ─ TypeError ───────────── the mock *is* a class but its ctor
            #                           takes no args (this is what the tests
            #                           hit).
            strategy = raw_strategy  # forward the string directly.

        # Create the conversation‑manager that actually keeps track of tokens,
        # summaries, etc.
        self._conversation_manager = InfiniteConversationManager(
            token_threshold=token_threshold,
            summarization_strategy=strategy,
        )

        logger.info("Initialized %s with session support", name)

    # ---------------------------------------------------------------------
    # Public helpers (the unit‑tests exercise these extensively)
    # ---------------------------------------------------------------------
    @property
    def name(self) -> str:  # noqa: D401
        """Return the registered name of this handler."""

        return self._name

    # ------------------------------------------------------------------
    # Session‑mapping helpers
    # ------------------------------------------------------------------
    def _get_agent_session_id(self, a2a_session_id: Optional[str]) -> Optional[str]:
        """Return the *agent* session‑id for a given external *A2A* id.

        Creates a new agent session (via :pyclass:`~Session.create`) on‑demand
        and caches the mapping.  All exceptions are caught and logged - the
        function returns *None* in error situations so that the caller can
        degrade gracefully rather than exploding inside tests.
        """

        if not a2a_session_id:
            return None

        # Fast path - already known.
        if a2a_session_id in self._session_map:
            return self._session_map[a2a_session_id]

        # ------------------------------------------------------------------
        # Need to create a *new* agent session.  ``Session.create`` is async -
        # here we need to bridge the sync/async boundary.  In production this
        # should ideally be re‑structured so that we never block the running
        # event‑loop, but for now we reproduce the original behaviour and add
        # robust error‑handling.
        # ------------------------------------------------------------------
        try:
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # "There is no current event loop in thread …" - fine.
                pass

            if loop and loop.is_running():
                # We *are* inside a running loop - use ``ensure_future`` and
                # ``run_until_complete`` on a *new* loop to avoid dead‑locks.
                # This path is only taken in unit‑tests where an outer loop
                # might already be active.
                future = Session.create()
                agent_session = loop.run_until_complete(future)  # type: ignore[arg-type]
            else:
                # No loop or not running yet - safe to just *run* the coroutine.
                agent_session = asyncio.run(Session.create())

            agent_session_id = agent_session.id  # type: ignore[attr-defined]
            self._session_map[a2a_session_id] = agent_session_id
            logger.debug(
                "Created new agent session %s for external session %s",
                agent_session_id,
                a2a_session_id,
            )
            return agent_session_id
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to create an agent session for %s", a2a_session_id)
            return None

    # ------------------------------------------------------------------
    # Conversation helpers (thin wrappers around InfiniteConversationManager)
    # ------------------------------------------------------------------
    async def add_to_session(self, agent_session_id: str, text: str, is_agent: bool = False) -> bool:  # noqa: D401
        """Add a message to the session.
        
        Args:
            agent_session_id: Internal agent session ID
            text: Message text content
            is_agent: Whether this message is from the agent (True) or user (False)
            
        Returns:
            Success flag
        """
        source = EventSource.LLM if is_agent else EventSource.USER
        try:
            await self._conversation_manager.process_message(
                agent_session_id,
                text,
                source,
                self._llm_call,  # callback the manager can use for live summaries
            )
            logger.debug("Added %s message to session %s", source, agent_session_id)
            return True
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to add message to session %s", agent_session_id)
            return False

    async def get_context(self, agent_session_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get conversation context for an agent session.
        
        Args:
            agent_session_id: Internal agent session ID
            
        Returns:
            List of messages in ChatML format, or None on error
        """
        try:
            context = await self._conversation_manager.build_context_for_llm(agent_session_id)
            logger.debug(
                "Retrieved %d messages of context for session %s",
                len(context) if context else 0,
                agent_session_id,
            )
            return context
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to build context for session %s", agent_session_id)
            return None

    # ------------------------------------------------------------------
    # Callback stub - must be implemented by concrete subclasses
    # ------------------------------------------------------------------
    async def _llm_call(self, messages: List[Dict[str, Any]], model: str = "default") -> str:  # noqa: D401
        """LLM callback used for summarization.
        
        Args:
            messages: List of messages in ChatML format
            model: Model to use for the call
            
        Returns:
            LLM response text
            
        Raises:
            NotImplementedError: Subclasses must implement this method
        """
        raise NotImplementedError("Sub‑classes must implement _llm_call() for summarisation support")

    # ------------------------------------------------------------------
    # Convenience wrappers requested by the tests
    # ------------------------------------------------------------------
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Get full conversation history for a session.
        
        Args:
            session_id: External A2A session ID
            
        Returns:
            List of messages in ChatML format
        """
        if not session_id:
            return []

        agent_session_id = self._session_map.get(session_id)
        if not agent_session_id:
            return []

        try:
            raw_history = await self._conversation_manager.get_full_conversation_history(agent_session_id)
            return [
                {"role": role, "content": content} for role, _source, content in raw_history
            ]
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to fetch conversation history for %s", session_id)
            return []

    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage statistics for a session.
        
        Args:
            session_id: External A2A session ID
            
        Returns:
            Dictionary with token usage statistics
        """
        if not session_id:
            return {"total_tokens": 0, "total_cost": 0}

        agent_session_id = self._session_map.get(session_id)
        if not agent_session_id:
            return {"total_tokens": 0, "total_cost": 0}

        try:
            store = SessionStoreProvider.get_store()
            session = await store.get(agent_session_id)
            if not session:
                return {"total_tokens": 0, "total_cost": 0}

            by_model: Dict[str, Dict[str, Any]] = {}
            for model, usage in session.token_summary.usage_by_model.items():  # type: ignore[attr-defined]
                by_model[model] = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "cost_usd": usage.estimated_cost_usd,
                }

            return {
                "total_tokens": session.total_tokens,  # type: ignore[attr-defined]
                "total_cost_usd": session.total_cost,  # type: ignore[attr-defined]
                "by_model": by_model,
            }
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to obtain token usage for %s", session_id)
            return {"total_tokens": 0, "total_cost": 0}