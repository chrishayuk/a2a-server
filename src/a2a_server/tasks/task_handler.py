# src/a2a_server/tasks/task_handler.py
import abc
from typing import Optional, AsyncIterable
from a2a_json_rpc.spec import (
    Message, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

class TaskHandler(abc.ABC):
    """Base interface for task handlers that process A2A tasks."""
    
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for this handler."""
        pass
        
    @property
    def supported_content_types(self) -> list[str]:
        """Content types this handler supports (default: text)."""
        return ["text/plain"]
    
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
