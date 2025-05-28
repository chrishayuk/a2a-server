# a2a_server/tasks/handlers/chuk/chuk_agent_handler.py
"""
Task handler that delegates processing to a ChukAgent instance.
"""
import importlib
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any

# a2a imports
from a2a_server.tasks.task_handler import TaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, TaskStatusUpdateEvent, 
    TaskArtifactUpdateEvent, Artifact, TextPart
)

logger = logging.getLogger(__name__)

class AgentHandler(TaskHandler):
    """
    Task handler that delegates processing to a ChukAgent instance defined in the YAML.
    
    This handler loads the agent specified in the YAML configuration
    and delegates tasks to it.
    """
    
    def __init__(self, agent=None, name="chuk_chef", **kwargs):
        """
        Initialize the agent handler.
        
        Args:
            agent: ChukAgent instance or string path to the agent module (from YAML config)
            name: Name of the handler (from YAML config)
            **kwargs: Additional arguments from YAML config
        """
        super().__init__()  # Initialize the parent TaskHandler
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
                    # Don't set self.agent to None here - it's already None
    
    @property
    def name(self) -> str:
        """Get the handler name."""
        return self._name
    
    @property
    def supported_content_types(self) -> List[str]:
        """Get supported content types."""
        return ["text/plain", "multipart/mixed"]
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator:
        """
        Process a task by delegating to the agent.
        
        Args:
            task_id: Unique identifier for the task
            message: The message to process
            session_id: Optional session identifier for maintaining conversation context
            **kwargs: Additional arguments that might be passed by the framework
        
        Yields:
            Task status and artifact updates from the agent
        """
        if self.agent is None:
            logger.error("No agent configured")
            # Fixed: Remove the message parameter since it's not allowed
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
            # Add an artifact with the error details instead
            yield TaskArtifactUpdateEvent(
                id=task_id,
                artifact=Artifact(
                    name="error",
                    parts=[TextPart(type="text", text="No agent configured")],
                    index=0
                )
            )
            return
            
        # Delegate processing to the agent
        try:
            async for event in self.agent.process_message(task_id, message, session_id):
                yield event
        except Exception as e:
            logger.error(f"Error in agent processing: {e}")
            # Fixed: Remove the message parameter since it's not allowed
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
            # Add an artifact with the error details instead
            yield TaskArtifactUpdateEvent(
                id=task_id,
                artifact=Artifact(
                    name="error",
                    parts=[TextPart(type="text", text=f"Agent error: {str(e)}")],
                    index=0
                )
            )
    
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
            Conversation history from the agent if available, otherwise empty list
        """
        if self.agent and hasattr(self.agent, 'get_conversation_history'):
            try:
                return await self.agent.get_conversation_history(session_id)
            except Exception as e:
                logger.error(f"Error getting conversation history: {e}")
                return []
        return []
    
    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get token usage statistics for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            Token usage statistics from the agent if available, otherwise empty stats
        """
        if self.agent and hasattr(self.agent, 'get_token_usage'):
            try:
                return await self.agent.get_token_usage(session_id)
            except Exception as e:
                logger.error(f"Error getting token usage: {e}")
                return {"total_tokens": 0, "total_cost": 0}
        return {"total_tokens": 0, "total_cost": 0}