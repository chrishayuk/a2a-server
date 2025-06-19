# a2a_server/tasks/handlers/chuk/chuk_agent_handler.py
"""
Handler that can load and work with both TaskHandler agents and pure ChukAgent instances.
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
    Handler that can work with both TaskHandler agents and pure ChukAgent instances.
    """
    
    # Mark as abstract to exclude from automatic discovery
    abstract = True
    
    def __init__(self, agent=None, name="agent_handler", **kwargs):
        """
        Initialize the agent handler.
        
        Args:
            agent: Agent instance or string path to agent module
            name: Name of the handler
            **kwargs: Additional arguments
        """
        self._name = name
        self.agent = self._load_agent(agent)
        self.is_chuk_agent = False
        
        if self.agent is None:
            logger.error(f"Failed to load agent for handler '{name}'")
        else:
            # Check if this is a ChukAgent (pure agent) vs TaskHandler agent
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            if isinstance(self.agent, ChukAgent):
                self.is_chuk_agent = True
                logger.info(f"Loaded ChukAgent '{self.agent.name}' for handler '{name}'")
            else:
                logger.info(f"Loaded TaskHandler agent for handler '{name}'")
    
    def _load_agent(self, agent_spec):
        """
        Load agent from specification.
        
        Args:
            agent_spec: Agent instance or import path string
            
        Returns:
            Agent instance
        """
        if agent_spec is None:
            return None
        
        # If already an instance, check what type it is
        if hasattr(agent_spec, '__class__'):
            from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
            
            # Pure ChukAgent - we'll adapt it
            if isinstance(agent_spec, ChukAgent):
                return agent_spec
            
            # TaskHandler agent - use directly  
            elif hasattr(agent_spec, 'process_task'):
                return agent_spec
            
            # Other agent types - try to use anyway
            else:
                logger.warning(f"Unknown agent type: {type(agent_spec)}, attempting to use")
                return agent_spec
        
        # If string, try to import
        if isinstance(agent_spec, str):
            try:
                module_path, _, attr = agent_spec.rpartition('.')
                module = importlib.import_module(module_path)
                agent = getattr(module, attr)
                return agent
                    
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
    
    def _extract_message_content(self, message: Message) -> str:
        """Extract text content from A2A message."""
        if not message.parts:
            return str(message) if message else "Empty message"
            
        text_parts = []
        for part in message.parts:
            try:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                elif hasattr(part, "model_dump"):
                    part_dict = part.model_dump()
                    if "text" in part_dict and part_dict["text"]:
                        text_parts.append(part_dict["text"])
            except Exception:
                pass
                
        return " ".join(text_parts) if text_parts else str(message)
    
    async def _process_with_chuk_agent(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Process task using pure ChukAgent."""
        # Yield working status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        try:
            # Extract user message
            user_content = self._extract_message_content(message)
            
            # Initialize tools
            await self.agent.initialize_tools()
            
            # Get available tools for enhanced instruction
            available_tools = await self.agent.get_available_tools()
            
            # Build enhanced instruction
            enhanced_instruction = self.agent.get_system_prompt()
            if available_tools:
                enhanced_instruction += f"\n\nYou have access to these tools: {', '.join(available_tools)}. Use them when appropriate to provide accurate, up-to-date information."
            
            # Prepare messages
            messages = [
                {"role": "system", "content": enhanced_instruction},
                {"role": "user", "content": user_content}
            ]
            
            # Use agent's complete method with session support
            result = await self.agent.complete(messages, use_tools=True, session_id=session_id)
            
            # Emit tool artifacts if tools were used
            if result["tool_calls"]:
                for i, (tool_call, tool_result) in enumerate(zip(result["tool_calls"], result["tool_results"])):
                    tool_artifact = Artifact(
                        name=f"tool_call_{i}",
                        parts=[TextPart(
                            type="text",
                            text=f"🔧 Tool: {tool_call.function.name}\n📥 Input: {tool_call.function.arguments}\n📤 Result: {tool_result.get('content', 'No result')}"
                        )],
                        index=i + 1
                    )
                    yield TaskArtifactUpdateEvent(id=task_id, artifact=tool_artifact)
            
            # Emit final response
            response_artifact = Artifact(
                name=f"{self.agent.name}_response",
                parts=[TextPart(type="text", text=result["content"] or "No response generated")],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=response_artifact)
            
            # Completion
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error processing task with ChukAgent: {e}")
            
            # Error artifact
            error_artifact = Artifact(
                name="error",
                parts=[TextPart(type="text", text=f"Error: {str(e)}")],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=error_artifact)
            
            # Failed status
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator:
        """
        Process a task by delegating to the appropriate agent type.
        
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
            # Handle ChukAgent instances with adapter logic
            if self.is_chuk_agent:
                async for event in self._process_with_chuk_agent(task_id, message, session_id):
                    yield event
            
            # Handle TaskHandler agents directly
            elif hasattr(self.agent, 'process_task'):
                async for event in self.agent.process_task(task_id, message, session_id, **kwargs):
                    yield event
            
            # Fallback for legacy agents with process_message
            elif hasattr(self.agent, 'process_message'):
                logger.warning(f"Agent uses legacy process_message interface")
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