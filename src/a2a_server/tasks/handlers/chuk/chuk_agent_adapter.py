# a2a_server/tasks/handlers/chuk/chuk_agent_adapter.py
"""
Adapter that wraps ChukAgent to work with A2A TaskHandler interface.
"""
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any

from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, TaskStatusUpdateEvent, 
    TaskArtifactUpdateEvent, Artifact, TextPart
)

logger = logging.getLogger(__name__)


class ChukAgentAdapter(TaskHandler):
    """
    Adapter that wraps a ChukAgent to work with the A2A TaskHandler interface.
    
    This keeps the ChukAgent pure and framework-agnostic while allowing it
    to work with the A2A task system.
    """
    
    def __init__(self, agent: ChukAgent):
        """
        Initialize the adapter with a ChukAgent.
        
        Args:
            agent: The ChukAgent instance to adapt
        """
        self.agent = agent
        
    @property
    def name(self) -> str:
        """Get the agent name."""
        return self.agent.name
    
    @property
    def supported_content_types(self) -> List[str]:
        """Get supported content types."""
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
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator:
        """
        Process a task by delegating to the ChukAgent.
        
        Args:
            task_id: Unique identifier for the task
            message: The message to process
            session_id: Optional session identifier
            **kwargs: Additional arguments
        
        Yields:
            Task status and artifact updates
        """
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
            
            # Use agent's complete method
            result = await self.agent.complete(messages, use_tools=True)
            
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
            logger.error(f"Error processing task: {e}")
            
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
    
    async def cancel_task(self, task_id: str) -> bool:
        """Attempt to cancel a running task."""
        logger.debug(f"Task cancellation not supported for {self.agent.name}")
        return False
    
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Get conversation history for a session."""
        # ChukAgent doesn't implement session management by default
        # This could be extended if needed
        return []
    
    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage statistics for a session."""
        # ChukAgent doesn't implement usage tracking by default
        # This could be extended if needed
        return {
            "total_tokens": 0,
            "estimated_cost": 0,
            "user_messages": 0,
            "ai_messages": 0,
            "session_segments": 0
        }


# Export the adapter
__all__ = ["ChukAgentAdapter"]