# a2a_server/tasks/handlers/chuk/chuk_agent_handler.py
"""
Simplified agent handler for modern CHUK agents.

Modern agents (ModernChukAgent) already implement TaskHandler interface,
so this handler is mainly for loading agents from YAML configuration.
"""
import importlib
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any

from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, TaskStatusUpdateEvent, 
    TaskArtifactUpdateEvent, Artifact, TextPart
)

logger = logging.getLogger(__name__)


class AgentHandler(TaskHandler):
    """
    Simplified handler that loads and delegates to modern CHUK agents.
    
    Modern agents already implement TaskHandler interface, so this mainly
    handles loading from YAML configuration and provides delegation.
    """
    
    # Mark as abstract to exclude from automatic discovery
    abstract = True
    
    def __init__(self, agent=None, name="modern_agent", **kwargs):
        """
        Initialize the agent handler.
        
        Args:
            agent: Agent instance or string path to agent module
            name: Name of the handler
            **kwargs: Additional arguments (passed to agent if needed)
        """
        self._name = name
        self.agent = self._load_agent(agent)
        
        if self.agent is None:
            logger.error(f"Failed to load agent for handler '{name}'")
        else:
            logger.info(f"Loaded agent '{self.agent.name}' for handler '{name}'")
    
    def _load_agent(self, agent_spec) -> Optional[TaskHandler]:
        """
        Load agent from specification.
        
        Args:
            agent_spec: Agent instance or import path string
            
        Returns:
            Agent instance that implements TaskHandler interface
        """
        if agent_spec is None:
            return None
        
        # If already an instance, verify it's a TaskHandler
        if hasattr(agent_spec, 'process_task'):
            if isinstance(agent_spec, TaskHandler):
                return agent_spec
            else:
                logger.warning(f"Agent instance does not inherit from TaskHandler: {type(agent_spec)}")
                return agent_spec  # Try to use it anyway
        
        # If string, try to import
        if isinstance(agent_spec, str):
            try:
                module_path, _, attr = agent_spec.rpartition('.')
                module = importlib.import_module(module_path)
                agent = getattr(module, attr)
                
                if isinstance(agent, TaskHandler):
                    return agent
                else:
                    logger.warning(f"Imported agent is not a TaskHandler: {type(agent)}")
                    return agent  # Try to use it anyway
                    
            except (ImportError, AttributeError) as e:
                logger.error(f"Failed to import agent from '{agent_spec}': {e}")
                return None
        
        logger.error(f"Invalid agent specification: {type(agent_spec)}")
        return None
    
    @property
    def name(self) -> str:
        """Get the handler name."""
        return self._name
    
    @property
    def supported_content_types(self) -> List[str]:
        """Get supported content types."""
        if self.agent and hasattr(self.agent, 'supported_content_types'):
            return self.agent.supported_content_types
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
            session_id: Optional session identifier
            **kwargs: Additional arguments
        
        Yields:
            Task status and artifact updates from the agent
        """
        if self.agent is None:
            logger.error(f"No agent configured for handler '{self.name}'")
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
            yield TaskArtifactUpdateEvent(
                id=task_id,
                artifact=Artifact(
                    name="error",
                    parts=[TextPart(type="text", text=f"No agent configured for handler '{self.name}'")],
                    index=0
                )
            )
            return
        
        try:
            # Modern agents implement process_task directly
            if hasattr(self.agent, 'process_task'):
                async for event in self.agent.process_task(task_id, message, session_id, **kwargs):
                    yield event
            # Fallback for legacy agents with process_message
            elif hasattr(self.agent, 'process_message'):
                logger.warning(f"Agent '{self.agent.name}' uses legacy process_message interface")
                async for event in self.agent.process_message(task_id, message, session_id):
                    yield event
            else:
                raise AttributeError(f"Agent does not implement process_task or process_message")
                
        except Exception as e:
            logger.exception(f"Error in agent processing for '{self.name}': {e}")
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
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
            Result from agent's cancel_task method, or False if not supported
        """
        if self.agent and hasattr(self.agent, 'cancel_task'):
            try:
                return await self.agent.cancel_task(task_id)
            except Exception as e:
                logger.error(f"Error cancelling task {task_id}: {e}")
                return False
        
        logger.debug(f"Task cancellation not supported for handler '{self.name}'")
        return False
    
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get conversation history for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            Conversation history from the agent if available
        """
        if self.agent and hasattr(self.agent, 'get_conversation_history'):
            try:
                return await self.agent.get_conversation_history(session_id)
            except Exception as e:
                logger.error(f"Error getting conversation history from '{self.name}': {e}")
        return []
    
    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get token usage statistics for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            Token usage statistics from the agent if available
        """
        if self.agent and hasattr(self.agent, 'get_token_usage'):
            try:
                return await self.agent.get_token_usage(session_id)
            except Exception as e:
                logger.error(f"Error getting token usage from '{self.name}': {e}")
        
        return {
            "total_tokens": 0,
            "estimated_cost": 0,
            "user_messages": 0,
            "ai_messages": 0,
            "session_segments": 0
        }


# For backward compatibility - this will be the main export
class ChukAgentHandler(AgentHandler):
    """Alias for AgentHandler to maintain backward compatibility."""
    # Also mark as abstract
    abstract = True