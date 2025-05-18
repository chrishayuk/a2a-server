
# File: a2a_server/tasks/handlers/adk/session_enabled_adk_handler.py
import asyncio
import logging
from typing import Dict, List, Optional, Any, AsyncIterable

from a2a_json_rpc.spec import (
    Message,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent
)

# Fix the import path to use the correct location
from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler
from a2a_server.tasks.handlers.adk.google_adk_protocol import GoogleADKAgentProtocol

logger = logging.getLogger(__name__)

class SessionEnabledADKHandler(SessionAwareTaskHandler):
    """
    Session-enabled implementation of Google ADK handler.
    
    This is used by the GoogleADKHandler when session support is enabled.
    """
    
    def __init__(
        self, 
        agent: GoogleADKAgentProtocol,
        name: str,
        session_store=None,
        token_threshold: int = 4000,
        summarization_strategy: str = "key_points"
    ):
        """Initialize with the given agent and session parameters."""
        super().__init__(
            name=name,
            session_store=session_store,
            token_threshold=token_threshold,
            summarization_strategy=summarization_strategy
        )
        self._agent = agent
    
    async def _llm_call(self, messages: List[Dict[str, Any]], model: str = "default") -> str:
        """
        Implementation of LLM call for summarization.
        
        Uses the ADK agent to generate summaries.
        
        Args:
            messages: List of messages in ChatML format
            model: Model name (ignored, uses agent's model)
            
        Returns:
            Summary text
        """
        # Check if this is a summary request
        if messages and messages[-1].get("role") == "system" and "summarize" in messages[-1].get("content", "").lower():
            prompt = "Please summarize the following conversation:\n\n"
            for msg in messages[:-1]:  # Skip the system message
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                prompt += f"{role.upper()}: {content}\n\n"
                
            try:
                return await asyncio.to_thread(self._agent.invoke, prompt)
            except Exception as e:
                logger.error(f"Error generating summary: {e}")
                return "Error generating summary."
        
        # For regular messages, just use the last user message
        last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if last_user_msg:
            try:
                return await asyncio.to_thread(self._agent.invoke, last_user_msg)
            except Exception as e:
                logger.error(f"Error in LLM call: {e}")
                return f"Error processing request: {str(e)}"
                
        return "I don't have enough context to respond."
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """
        Process a task (not directly used, as GoogleADKHandler handles processing).
        
        This is required by the TaskHandler interface but not used directly.
        """
        raise NotImplementedError("This method should not be called directly")