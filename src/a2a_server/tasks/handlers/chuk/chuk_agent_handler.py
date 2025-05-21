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

# Local imports
from .chuk_agent import ChukAgent
from .conversation_manager import ConversationManager
from .chuk_agent_adapter import ChukAgentAdapter

logger = logging.getLogger(__name__)

class ChukAgentHandler(TaskHandler):
    """
    Task handler that delegates processing to a ChukAgent instance.
    """
    
    def __init__(
        self, 
        agent=None, 
        name="chuk_agent_handler",
        use_sessions: bool = True,
        token_threshold: int = 4000,
        summarization_strategy: str = "key_points",
        streaming: bool = True
    ):
        """
        Initialize the agent handler.
        
        Args:
            agent: ChukAgent instance or string path to the agent module
            name: Name of the handler
            use_sessions: Whether to enable conversation memory
            token_threshold: Maximum tokens before session segmentation
            summarization_strategy: Strategy for summarizing sessions
            streaming: Whether to use streaming responses
        """
        self._name = name
        self.agent = None
        self.conversation_manager = None
        self.adapter = None
        
        if agent:
            # Check if agent is already a ChukAgent instance
            if isinstance(agent, ChukAgent):
                self.agent = agent
                logger.info(f"Using provided ChukAgent instance")
            # Check if agent is a string import path
            elif isinstance(agent, str):
                try:
                    module_path, _, attr = agent.rpartition('.')
                    module = importlib.import_module(module_path)
                    agent_obj = getattr(module, attr)
                    
                    # Check if the imported object is a ChukAgent instance
                    if isinstance(agent_obj, ChukAgent):
                        self.agent = agent_obj
                        logger.info(f"Loaded ChukAgent from {agent}")
                    else:
                        logger.warning(f"Imported object is not a ChukAgent instance, skipping")
                except (ImportError, AttributeError) as e:
                    logger.error(f"Failed to load agent from {agent}: {e}")
            else:
                logger.error(f"Unsupported agent type: {type(agent)}")
        
        # Initialize conversation manager if requested
        if use_sessions and self.agent:
            try:
                self.conversation_manager = ConversationManager(
                    token_threshold=token_threshold,
                    summarization_strategy=summarization_strategy,
                    agent=self.agent
                )
                logger.info(f"Initialized conversation manager with threshold {token_threshold}")
            except Exception as e:
                logger.error(f"Failed to initialize conversation manager: {e}")
                self.conversation_manager = None
        
        # Create the adapter if we have an agent
        if self.agent:
            self.adapter = ChukAgentAdapter(
                agent=self.agent,
                conversation_manager=self.conversation_manager,
                streaming=streaming
            )
            logger.info(f"Initialized adapter for agent '{self.agent.name}'")
    
    @property
    def name(self) -> str:
        """Get the handler name."""
        return self._name
    
    @property
    def supported_content_types(self) -> List[str]:
        """Get supported content types."""
        return ["text/plain"]
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """
        Process a task by delegating to the agent adapter.
        
        Args:
            task_id: Unique identifier for the task
            message: The message to process
            session_id: Optional session identifier for maintaining conversation context
        
        Yields:
            Task status and artifact updates from the agent
        """
        if self.agent is None or self.adapter is None:
            logger.error("No agent or adapter configured")
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed, message="No agent configured"),
                final=True
            )
            return
            
        # Delegate processing to the adapter
        async for event in self.adapter.process_message(task_id, message, session_id):
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
            A list of messages in ChatML format
        """
        if self.conversation_manager and session_id:
            return await self.conversation_manager.get_conversation_history(session_id)
        return []
    
    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get token usage statistics for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            A dictionary with token usage statistics
        """
        if self.conversation_manager and session_id:
            return await self.conversation_manager.get_token_usage(session_id)
        return {"total_tokens": 0, "total_cost": 0}