# a2a_server/tasks/handlers/task_handler.py
"""
Enhanced base task handler interface with comprehensive capabilities.
"""
from __future__ import annotations
import abc
import logging
from typing import Optional, AsyncIterable, List, Dict, Any
from datetime import datetime, timezone

from a2a_json_rpc.spec import (
    Message, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

logger = logging.getLogger(__name__)


class TaskHandler(abc.ABC):
    """
    Enhanced base interface for task handlers that process A2A tasks.
    
    This base class provides a comprehensive interface for task processing
    with support for sessions, health monitoring, and capability detection.
    """
    
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for this handler."""
        pass
    
    @property
    def supported_content_types(self) -> List[str]:
        """Content types this handler supports (default: text)."""
        return ["text/plain"]
    
    @property
    def streaming(self) -> bool:
        """Whether this handler supports streaming responses."""
        return False
    
    @property
    def supports_sessions(self) -> bool:
        """Whether this handler supports session management."""
        return hasattr(self, 'get_conversation_history') or hasattr(self, 'session_sharing')
    
    @property
    def supports_tools(self) -> bool:
        """Whether this handler supports tool usage."""
        return getattr(self, 'enable_tools', False)
    
    @property
    def supports_cancellation(self) -> bool:
        """Whether this handler supports task cancellation."""
        return hasattr(self, 'cancel_task')
    
    @abc.abstractmethod
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """
        Process a task asynchronously and yield status/artifact events.
        
        Args:
            task_id: Unique ID for the task
            message: The user message to process
            session_id: Optional session context
            
        Yields:
            Events as the task progresses
        """
        pass
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Attempt to cancel a running task.
        
        Args:
            task_id: ID of task to cancel
            
        Returns:
            True if successfully cancelled, False otherwise
        """
        return False
    
    # Optional session management interface
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get conversation history for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of conversation messages
        """
        return []
    
    async def get_conversation_context(
        self, 
        session_id: Optional[str] = None, 
        max_messages: int = 10
    ) -> List[Dict[str, str]]:
        """
        Get recent conversation context.
        
        Args:
            session_id: Session identifier
            max_messages: Maximum number of messages to return
            
        Returns:
            List of recent conversation messages
        """
        history = await self.get_conversation_history(session_id)
        return history[-max_messages:] if history else []
    
    async def add_user_message(self, session_id: Optional[str], message: str) -> bool:
        """
        Add a user message to the session.
        
        Args:
            session_id: Session identifier
            message: User message content
            
        Returns:
            True if successful, False otherwise
        """
        return True  # Default no-op implementation
    
    async def add_ai_response(
        self, 
        session_id: Optional[str], 
        response: str,
        model: str = "unknown",
        provider: str = "unknown"
    ) -> bool:
        """
        Add an AI response to the session.
        
        Args:
            session_id: Session identifier
            response: AI response content
            model: Model used for the response
            provider: Provider used for the response
            
        Returns:
            True if successful, False otherwise
        """
        return True  # Default no-op implementation
    
    async def cleanup_session(self, session_id: str) -> bool:
        """
        Clean up session resources.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if successful, False otherwise
        """
        return True  # Default no-op implementation
    
    # Optional health and monitoring interface
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status information for this handler.
        
        Returns:
            Dictionary containing health status information
        """
        return {
            "status": "healthy",
            "handler_name": self.name,
            "capabilities": {
                "sessions": self.supports_sessions,
                "tools": self.supports_tools,
                "streaming": self.streaming,
                "cancellation": self.supports_cancellation,
                "content_types": self.supported_content_types
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    def get_session_stats(self) -> Dict[str, Any]:
        """
        Get session-related statistics.
        
        Returns:
            Dictionary containing session statistics
        """
        return {
            "handler_name": self.name,
            "session_support": self.supports_sessions,
            "session_sharing": getattr(self, 'session_sharing', False),
            "sandbox_id": getattr(self, 'sandbox_id', None),
            "shared_sandbox_group": getattr(self, 'shared_sandbox_group', None)
        }
    
    def validate_configuration(self) -> Dict[str, Any]:
        """
        Validate this handler's configuration.
        
        Returns:
            Validation results with any issues found
        """
        validation = {
            "handler_name": self.name,
            "configuration_valid": True,
            "issues": [],
            "warnings": []
        }
        
        # Check basic interface requirements
        if not hasattr(self, 'process_task'):
            validation["configuration_valid"] = False
            validation["issues"].append("Missing required 'process_task' method")
        
        # Check session configuration if applicable
        if self.supports_sessions:
            if hasattr(self, 'session_sharing') and hasattr(self, 'shared_sandbox_group'):
                if self.session_sharing and not self.shared_sandbox_group:
                    validation["issues"].append("Session sharing enabled but no shared_sandbox_group specified")
                elif not self.session_sharing and self.shared_sandbox_group:
                    validation["warnings"].append("shared_sandbox_group specified but session sharing disabled")
        
        # Check content type configuration
        if not self.supported_content_types:
            validation["warnings"].append("No supported content types specified")
        
        return validation
    
    async def initialize(self) -> None:
        """
        Initialize the handler (called during startup).
        
        Override this method to perform any initialization tasks.
        """
        pass
    
    async def shutdown(self) -> None:
        """
        Shutdown the handler (called during cleanup).
        
        Override this method to perform any cleanup tasks.
        """
        pass
    
    def __str__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
    
    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"name='{self.name}', "
                f"sessions={self.supports_sessions}, "
                f"tools={self.supports_tools}, "
                f"streaming={self.streaming})")


__all__ = [
    "TaskHandler"
]