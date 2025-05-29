# a2a_server/tasks/handlers/chuk/conversation_manager.py
"""
ConversationManager: Handles conversation session management.
"""
import logging
from typing import Dict, List, Any, Optional

# Import session manager components
try:
    from chuk_session_manager.storage import SessionStoreProvider, InMemorySessionStore
    from chuk_session_manager.infinite_conversation import (
        InfiniteConversationManager, SummarizationStrategy
    )
    from chuk_session_manager.models.session import Session
    from chuk_session_manager.models.event_source import EventSource
    from chuk_session_manager.models.event_type import EventType
    from chuk_session_manager.models.session import SessionEvent
    
    SESSION_MANAGER_AVAILABLE = True
except ImportError:
    SESSION_MANAGER_AVAILABLE = False

logger = logging.getLogger(__name__)

class ConversationManager:
    """
    Handles conversation session management.
    """
    
    def __init__(
        self,
        token_threshold: int = 4000,
        summarization_strategy: str = "key_points",
        agent = None  # Optional agent for summarization
    ):
        """
        Initialize conversation manager with specific characteristics.
        
        Args:
            token_threshold: Maximum tokens before session segmentation
            summarization_strategy: Strategy for summarizing sessions
            agent: Optional agent for generating summaries
        """
        self.token_threshold = token_threshold
        self.summarization_strategy = summarization_strategy
        self.agent = agent
        
        # Session tracking
        self.session_map = {}  # Map external session IDs to internal session IDs
        self.session_failures = 0  # Track session failures for graceful degradation
        self.max_session_failures = 5  # Max failures before disabling session management
        
        # Import session manager components if available
        if SESSION_MANAGER_AVAILABLE:
            # Ensure we have a session store
            if not SessionStoreProvider.get_store():
                SessionStoreProvider.set_store(InMemorySessionStore())
            
            # Map string strategy to enum
            strategy_map = {
                "basic": SummarizationStrategy.BASIC,
                "key_points": SummarizationStrategy.KEY_POINTS,
                "query_focused": SummarizationStrategy.QUERY_FOCUSED,
                "topic_based": SummarizationStrategy.TOPIC_BASED
            }
            
            # Create the conversation manager from chuk_session_manager
            self.chuk_conversation_manager = InfiniteConversationManager(
                token_threshold=token_threshold,
                summarization_strategy=strategy_map.get(
                    summarization_strategy.lower(), 
                    SummarizationStrategy.KEY_POINTS
                )
            )
            
            self.available = True
            logger.info(f"Initialized conversation manager with token threshold {token_threshold}")
        else:
            logger.warning("chuk_session_manager not available - session management disabled")
            self.chuk_conversation_manager = None
            self.available = False
    
    async def generate_summary(self, messages: List[Dict[str, Any]]) -> str:
        """
        Generate a summary of the conversation using the agent.
        
        Args:
            messages: The conversation history to summarize
            
        Returns:
            A summary of the conversation
        """
        if not self.agent:
            return "No summary generated (no agent available)"
            
        # Create a system prompt for summarization
        system_prompt = """
        Create a concise summary of the conversation below.
        Focus on key points and main topics of the discussion.
        Format your response as a brief paragraph.
        """
        
        # Prepare messages for the LLM
        summary_messages = [
            {"role": "system", "content": system_prompt},
        ]
        
        # Add relevant conversation messages
        for msg in messages:
            if msg["role"] != "system":
                summary_messages.append(msg)
        
        # Get the summary from the agent
        try:
            response = await self.agent.generate_response(summary_messages)
            
            # Check if we got a streaming response or a complete response
            if hasattr(response, "get"):
                # Complete response object
                summary = response.get("response", "No summary generated")
            else:
                # In case we got a string or other response
                summary = str(response)
                
            return summary
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "Error generating summary"
    
    async def get_or_create_session(self, external_session_id: str) -> Optional[str]:
        """
        Get or create a session ID.
        
        Args:
            external_session_id: The external session ID
            
        Returns:
            An internal session ID or None if unavailable
        """
        if not self.available:
            return None
            
        try:
            # Create a new session if we haven't seen this ID before
            if external_session_id not in self.session_map:
                new_session = await Session.create()
                self.session_map[external_session_id] = new_session.id
                logger.info(f"Created new session {new_session.id} for external session {external_session_id}")
                return new_session.id
            
            # Get the existing session ID from our map
            internal_session_id = self.session_map[external_session_id]
            
            # Retrieve the session from the store
            store = SessionStoreProvider.get_store()
            session = await store.get(internal_session_id)
            if session:
                return internal_session_id
            else:
                # If session not found, create a new one
                new_session = await Session.create()
                self.session_map[external_session_id] = new_session.id
                return new_session.id
                
        except Exception as e:
            self.session_failures += 1
            logger.error(f"Error in get_or_create_session: {str(e)}")
            
            # Disable session management if too many failures
            if self.session_failures >= self.max_session_failures:
                logger.warning(f"Too many session failures ({self.session_failures}), disabling session management")
                self.available = False
                return None
                
            # Fallback to creating a new session on error
            try:
                new_session = await Session.create()
                self.session_map[external_session_id] = new_session.id
                return new_session.id
            except Exception as inner_e:
                logger.error(f"Failed to create fallback session: {str(inner_e)}")
                return None
    
    async def add_message(
        self, 
        external_session_id: str, 
        message: str, 
        is_agent: bool = False
    ) -> bool:
        """
        Add a message to the session.
        
        Args:
            external_session_id: The external session ID
            message: The message content
            is_agent: Whether the message is from the agent
            
        Returns:
            True if the message was added successfully, False otherwise
        """
        if not self.available:
            return False
            
        try:
            # Get or create the internal session ID
            internal_session_id = await self.get_or_create_session(external_session_id)
            if not internal_session_id:
                return False
            
            # Add the message to the session
            store = SessionStoreProvider.get_store()
            session = await store.get(internal_session_id)
            
            if session:
                await session.add_event_and_save(
                    SessionEvent(
                        message=message,
                        source=EventSource.LLM if is_agent else EventSource.USER,
                        type=EventType.MESSAGE
                    )
                )
                return True
            else:
                logger.warning(f"Session {internal_session_id} not found for adding message")
                return False
                
        except Exception as e:
            self.session_failures += 1
            logger.error(f"Error adding message to session: {str(e)}")
            
            # Disable session management if too many failures
            if self.session_failures >= self.max_session_failures:
                logger.warning(f"Too many session failures ({self.session_failures}), disabling session management")
                self.available = False
                
            return False
    
    async def get_context(self, external_session_id: str) -> List[Dict[str, str]]:
        """
        Get the conversation context for an external session ID.
        
        Args:
            external_session_id: The external session ID
            
        Returns:
            A list of messages in ChatML format
        """
        if not self.available:
            return []
            
        try:
            # Get the internal session ID
            internal_session_id = self.session_map.get(external_session_id)
            if not internal_session_id:
                return []
                
            # Build context from the session
            context = await self.chuk_conversation_manager.build_context_for_llm(internal_session_id)
            
            return context
                
        except Exception as e:
            logger.error(f"Error getting context: {str(e)}")
            return []
    
    async def get_conversation_history(self, external_session_id: str) -> List[Dict[str, str]]:
        """
        Get the full conversation history for an external session ID.
        
        Args:
            external_session_id: The external session ID
            
        Returns:
            A list of messages in ChatML format
        """
        if not self.available:
            return []
            
        try:
            # Get the internal session ID
            internal_session_id = self.session_map.get(external_session_id)
            if not internal_session_id:
                return []
                
            # Get the full conversation history
            history = await self.chuk_conversation_manager.get_full_conversation_history(internal_session_id)
            
            # Convert to ChatML format
            formatted_history = []
            for role, source, content in history:
                formatted_history.append({
                    "role": role,
                    "content": content
                })
            
            return formatted_history
                
        except Exception as e:
            logger.error(f"Error getting conversation history: {str(e)}")
            return []
    
    async def get_token_usage(self, external_session_id: str) -> Dict[str, Any]:
        """
        Get token usage statistics for an external session ID.
        
        Args:
            external_session_id: The external session ID
            
        Returns:
            A dictionary with usage statistics
        """
        if not self.available:
            return {"total_tokens": 0, "total_cost": 0}
            
        try:
            # Get the internal session ID
            internal_session_id = self.session_map.get(external_session_id)
            if not internal_session_id:
                return {"total_tokens": 0, "total_cost": 0}
                
            # Get the session from the store
            store = SessionStoreProvider.get_store()
            session = await store.get(internal_session_id)
            
            if not session:
                return {"total_tokens": 0, "total_cost": 0}
                
            # Get usage statistics
            usage = {
                "total_tokens": session.total_tokens,
                "total_cost": session.total_cost,
                "by_model": {}
            }
            
            # Add model-specific usage
            for model, model_usage in session.token_summary.usage_by_model.items():
                usage["by_model"][model] = {
                    "prompt_tokens": model_usage.prompt_tokens,
                    "completion_tokens": model_usage.completion_tokens,
                    "total_tokens": model_usage.total_tokens,
                    "cost": model_usage.estimated_cost_usd
                }
            
            # Add source-specific usage
            source_usage = await session.get_token_usage_by_source()
            usage["by_source"] = {}
            for source, summary in source_usage.items():
                usage["by_source"][source] = {
                    "total_tokens": summary.total_tokens,
                    "cost": summary.total_estimated_cost_usd
                }
            
            return usage
                
        except Exception as e:
            logger.error(f"Error getting token usage: {str(e)}")
            return {"total_tokens": 0, "total_cost": 0}