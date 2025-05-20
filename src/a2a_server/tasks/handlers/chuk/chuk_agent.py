"""
ChukAgent: A simplified agent abstraction using chuk-llm for a2a server integration.
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional, Union, AsyncGenerator

# a2a imports
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

# chuk-llm imports
from chuk_llm.llm.llm_client import get_llm_client
from chuk_llm.llm.provider_config import ProviderConfig

logger = logging.getLogger(__name__)

class ChukAgent:
    """
    A high-level agent abstraction using chuk-llm for a2a server integration.
    
    This class simplifies creating agents with different personalities
    and instructions while handling LLM interactions.
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        instruction: str = "",
        provider: str = "openai",
        model: Optional[str] = None,
        streaming: bool = True,
        config: Optional[ProviderConfig] = None
    ):
        """
        Initialize a new agent with specific characteristics.
        
        Args:
            name: Unique identifier for this agent
            description: Brief description of the agent's purpose
            instruction: System prompt defining the agent's personality and constraints
            provider: LLM provider to use (openai, anthropic, gemini, etc.)
            model: Specific model to use (if None, uses provider default)
            streaming: Whether to stream responses or return complete responses
            config: Optional provider configuration
        """
        self.name = name
        self.description = description
        self.instruction = instruction
        self.provider = provider
        self.model = model
        self.streaming = streaming
        self.config = config or ProviderConfig()
        
        logger.info(f"Initialized agent '{name}' using {provider}/{model or 'default'}")
    
    async def process_message(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """
        Process a message and generate responses.
        
        Args:
            task_id: Unique identifier for the task
            message: Message to process
            session_id: Optional session identifier for maintaining conversation context
        
        Yields:
            Task status and artifact updates
        """
        # First yield a "working" status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        # Initialize LLM client
        client = get_llm_client(
            provider=self.provider,
            model=self.model,
            config=self.config
        )
        
        # Format messages for the LLM
        llm_messages = self._format_messages(message, session_id)
        
        # Track response state
        started_generating = False
        full_response = ""
        
        try:
            if self.streaming:
                # Streaming mode
                stream = await client.create_completion(
                    messages=llm_messages,
                    stream=True
                )
                
                # Process streaming response
                async for chunk in stream:
                    # Extract delta text
                    delta = chunk.get("response", "")
                    
                    # Handle text response
                    if delta:
                        full_response += delta
                        
                        # Create/update response artifact
                        if not started_generating:
                            started_generating = True
                            artifact = Artifact(
                                name=f"{self.name}_response",
                                parts=[TextPart(type="text", text=delta)],
                                index=0
                            )
                        else:
                            artifact = Artifact(
                                name=f"{self.name}_response",
                                parts=[TextPart(type="text", text=full_response)],
                                index=0
                            )
                        
                        yield TaskArtifactUpdateEvent(
                            id=task_id,
                            artifact=artifact
                        )
                        
                        # Small delay to avoid overwhelming the client
                        await asyncio.sleep(0.01)
            else:
                # Non-streaming mode
                response = await client.create_completion(
                    messages=llm_messages,
                    stream=False
                )
                
                # Extract text response
                text_response = response.get("response", "")
                
                # Create response artifact
                yield TaskArtifactUpdateEvent(
                    id=task_id,
                    artifact=Artifact(
                        name=f"{self.name}_response",
                        parts=[TextPart(type="text", text=text_response or "")],
                        index=0
                    )
                )
            
            # Complete the task
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error in agent '{self.name}': {e}")
            
            # Yield error status
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(
                    state=TaskState.error,
                    message=f"Agent Error: {str(e)}"
                ),
                final=True
            )
    
    def _format_messages(self, message: Message, session_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        Format a2a message into LLM messages format.
        
        Args:
            message: The a2a message to process
            session_id: Optional session ID for conversation context
        
        Returns:
            List of messages in the format expected by chuk-llm
        """
        formatted_messages = []
        
        # Add system message with instruction
        if self.instruction:
            formatted_messages.append({
                "role": "system",
                "content": self.instruction
            })
        
        # TODO: Add conversation history if session_id is provided
        
        # Extract content from the message
        content = self._extract_message_content(message)
        
        # Add the user message
        formatted_messages.append({
            "role": "user",
            "content": content
        })
        
        return formatted_messages
    
    def _extract_message_content(self, message: Message) -> Union[str, List[Dict[str, Any]]]:
        """
        Extract content from message parts, handling both text and multimodal inputs.
        
        Args:
            message: The a2a message to extract content from
            
        Returns:
            Either a string (for text-only messages) or a list of content parts
        """
        if not message.parts:
            return ""
            
        # Check if any non-text parts exist
        has_non_text = any(part.type != "text" for part in message.parts if hasattr(part, "type"))
        
        if not has_non_text:
            # Simple text case - concatenate all text parts
            return " ".join(
                part.model_dump().get("text", "") 
                for part in message.parts 
                if hasattr(part, "text") and part.text
            )
        
        # Multimodal case - create a list of content parts
        content_parts = []
        
        for part in message.parts:
            part_data = part.model_dump(exclude_none=True)
            
            if part.type == "text" and "text" in part_data:
                content_parts.append({
                    "type": "text",
                    "text": part_data["text"]
                })
            elif part.type == "image" and "data" in part_data:
                # Handle image data
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{part_data['data']}"
                    }
                })
            # Additional part types can be handled here
        
        return content_parts