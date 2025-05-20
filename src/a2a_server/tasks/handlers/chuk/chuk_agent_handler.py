"""
Task handler that delegates processing to a ChukAgent instance.
"""
import importlib
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any

# a2a imports
from a2a_server.tasks.task_handler import TaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, TaskStatusUpdateEvent
)

logger = logging.getLogger(__name__)

class AgentHandler(TaskHandler):
    """
    Task handler that delegates processing to a ChukAgent instance defined in the YAML.
    
    This handler loads the agent specified in the YAML configuration
    and delegates tasks to it.
    """
    
    def __init__(self, agent=None, name="chuk_chef"):
        """
        Initialize the agent handler.
        
        Args:
            agent: ChukAgent instance or string path to the agent module (from YAML config)
            name: Name of the handler (from YAML config)
        """
        self.agent = None
        self._name = name
        
        if agent:
            # Check if agent is already an object (instance)
            if hasattr(agent, 'process_message'):
                self.agent = agent
                logger.info(f"Using provided agent instance")
            else:
                # Otherwise, treat it as a string import path
                try:
                    module_path, _, attr = agent.rpartition('.')
                    module = importlib.import_module(module_path)
                    self.agent = getattr(module, attr)
                    logger.info(f"Loaded agent from {agent}")
                except (ImportError, AttributeError) as e:
                    logger.error(f"Failed to load agent from {agent}: {e}")
    
    @property
    def name(self) -> str:
        """Get the handler name."""
        return self._name
    
    @property
    def supported_content_types(self) -> List[str]:
        """Get supported content types."""
        return ["text/plain"]
    
    async def process_task(self, task_id: str, message: Message, 
                          session_id: Optional[str] = None) -> AsyncGenerator:
        """
        Process a task by delegating to the agent.
        
        Args:
            task_id: Unique identifier for the task
            message: The message to process
            session_id: Optional session identifier for maintaining conversation context
        
        Yields:
            Task status and artifact updates from the agent
        """
        if self.agent is None:
            logger.error("No agent configured")
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.error, message="No agent configured"),
                final=True
            )
            return
            
        # Delegate processing to the agent
        async for event in self.agent.process_message(task_id, message, session_id):
            yield event
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Attempt to cancel a running task.
        
        Args:
            task_id: The task ID to cancel
            
        Returns:
            Always False (not supported)
        """
        logger.debug(f"Cancellation request for task {task_id} - not supported")
        return False
    
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get conversation history for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            Empty list (sessions not supported)
        """
        return []
    
    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get token usage statistics for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            Dictionary with empty token usage statistics
        """
        return {"total_tokens": 0, "total_cost": 0}