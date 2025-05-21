"""
ChukAgentAdapter: Adapts a ChukAgent to the interface expected by A2A handlers.
"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, Union, AsyncGenerator

# a2a imports
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

# Local imports
from .chuk_agent import ChukAgent
from .conversation_manager import ConversationManager

logger = logging.getLogger(__name__)

class ChukAgentAdapter:
    """
    Adapts a ChukAgent to the interface expected by A2A handlers.
    """
    
    def __init__(
        self, 
        agent: ChukAgent, 
        conversation_manager: Optional[ConversationManager] = None,
        streaming: bool = True
    ):
        """
        Initialize adapter with an agent and optional conversation manager.
        
        Args:
            agent: The ChukAgent instance to adapt
            conversation_manager: Optional conversation manager for session history
            streaming: Whether to use streaming responses
        """
        self.agent = agent
        self.conversation_manager = conversation_manager
        self.streaming = streaming
        
        # Override agent streaming setting if needed
        if streaming != agent.streaming:
            agent.streaming = streaming
            
        logger.info(f"Initialized AgentAdapter for agent '{agent.name}'")
    
    def _extract_message_content(self, message: Message) -> Union[str, List[Dict[str, Any]]]:
        """
        Extract content from message parts, handling both text and multimodal inputs.
        
        Args:
            message: The a2a message to extract content from
            
        Returns:
            Either a string (for text-only messages) or a list of content parts
        """
        # Try to get message dump for extraction
        try:
            if hasattr(message, 'model_dump'):
                message_dump = message.model_dump()
                
                # Check for content field directly
                if hasattr(message, 'content'):
                    return message.content
                    
                # Check for text field directly
                if hasattr(message, 'text'):
                    return message.text
        except Exception:
            pass
        
        # Fallback to parts extraction
        if not message.parts:
            # Try direct string conversion as last resort
            try:
                content = str(message)
                return content if content else "Empty message"
            except:
                return "Empty message"
            
        # Check if any non-text parts exist
        has_non_text = any(part.type != "text" for part in message.parts if hasattr(part, "type"))
        
        if not has_non_text:
            # Simple text case - concatenate all text parts
            text_parts = []
            for part in message.parts:
                try:
                    # Try multiple approaches to extract text
                    if hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
                    elif hasattr(part, "model_dump"):
                        part_dict = part.model_dump()
                        if "text" in part_dict and part_dict["text"]:
                            text_parts.append(part_dict["text"])
                    elif hasattr(part, "to_dict"):
                        part_dict = part.to_dict()
                        if "text" in part_dict and part_dict["text"]:
                            text_parts.append(part_dict["text"])
                    # Last resort - try __str__
                    else:
                        part_str = str(part)
                        text_parts.append(part_str)
                except Exception:
                    pass
                    
            # Handle empty parts
            if not text_parts:
                # Try one more fallback using string representation
                try:
                    return str(message)
                except:
                    return "Empty message"
                
            return " ".join(text_parts)
        
        # Multimodal case - create a list of content parts
        content_parts = []
        
        for part in message.parts:
            try:
                part_data = part.model_dump(exclude_none=True) if hasattr(part, "model_dump") else {}
                
                if hasattr(part, "type") and part.type == "text":
                    if hasattr(part, "text") and part.text:
                        content_parts.append({
                            "type": "text",
                            "text": part.text
                        })
                    elif "text" in part_data:
                        content_parts.append({
                            "type": "text",
                            "text": part_data["text"]
                        })
                elif hasattr(part, "type") and part.type == "image":
                    if hasattr(part, "data") and part.data:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{part.data}"
                            }
                        })
                    elif "data" in part_data:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{part_data['data']}"
                            }
                        })
            except Exception:
                pass
        
        # Fallback if no parts could be processed
        if not content_parts:
            try:
                return str(message)
            except:
                return "Empty multimodal message"
                
        return content_parts
    
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
        
        # Extract the user message content
        raw_user_content = self._extract_message_content(message)
        
        # Convert to string if needed
        if isinstance(raw_user_content, list):
            user_content_str = json.dumps(raw_user_content)
        else:
            user_content_str = raw_user_content
        
        # Ensure we don't have empty content
        if not user_content_str or user_content_str.strip() == "" or user_content_str == "Empty message":
            # Try to recover from the message object itself
            try:
                # Access raw parts if available
                if hasattr(message, 'parts') and message.parts:
                    part_texts = []
                    for part in message.parts:
                        if hasattr(part, '_obj') and hasattr(part._obj, 'get'):
                            text = part._obj.get('text')
                            if text:
                                part_texts.append(text)
                    
                    if part_texts:
                        user_content_str = " ".join(part_texts)
                
                # If still empty, try message.__dict__
                if not user_content_str or user_content_str.strip() == "":
                    if hasattr(message, '__dict__'):
                        for attr_name, attr_value in message.__dict__.items():
                            if isinstance(attr_value, str) and attr_value.strip():
                                user_content_str = attr_value
                                break
                        
                    # Last resort - use the string representation
                    if not user_content_str or user_content_str.strip() == "":
                        user_content_str = str(message)
            except Exception:
                pass
                
            # If still empty, use a placeholder
            if not user_content_str or user_content_str.strip() == "":
                user_content_str = f"Message from user at {task_id[-8:]}"
        
        # Prepare messages for the LLM
        llm_messages = []
        
        # Use the conversation manager if available
        if self.conversation_manager and session_id:
            try:
                # Add the user message to the session
                await self.conversation_manager.add_message(
                    session_id, 
                    user_content_str, 
                    is_agent=False
                )
                
                # Get context from the session
                context = await self.conversation_manager.get_context(session_id)
                if context:
                    llm_messages = context
                else:
                    llm_messages = [{"role": "system", "content": self.agent.instruction}]
            except Exception as e:
                logger.error(f"Error using conversation manager: {e}")
                llm_messages = [{"role": "system", "content": self.agent.instruction}]
        else:
            # Basic formatting without conversation manager
            llm_messages = [{"role": "system", "content": self.agent.instruction}]
        
        # Add the current user message if not already in context
        if not llm_messages or llm_messages[-1].get("role") != "user":
            llm_messages.append({"role": "user", "content": user_content_str})
        
        # Track response state
        started_generating = False
        full_response = ""
        
        try:
            # Generate response with the agent
            response_generator = await self.agent.generate_response(llm_messages)
            
            if self.streaming and hasattr(response_generator, "__aiter__"):
                # Process streaming response
                async for chunk in response_generator:
                    # Extract delta text
                    delta = chunk.get("response", "")
                    
                    # Handle text response
                    if delta:
                        full_response += delta
                        
                        # Create/update response artifact
                        if not started_generating:
                            started_generating = True
                            artifact = Artifact(
                                name=f"{self.agent.name}_response",
                                parts=[TextPart(type="text", text=delta)],
                                index=0
                            )
                        else:
                            artifact = Artifact(
                                name=f"{self.agent.name}_response",
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
                # Non-streaming mode or received complete response
                if hasattr(response_generator, "get"):
                    # Complete response object
                    text_response = response_generator.get("response", "")
                else:
                    # In case we got a string or other non-dict response
                    text_response = str(response_generator)
                
                full_response = text_response
                
                # Create response artifact
                yield TaskArtifactUpdateEvent(
                    id=task_id,
                    artifact=Artifact(
                        name=f"{self.agent.name}_response",
                        parts=[TextPart(type="text", text=text_response or "")],
                        index=0
                    )
                )
            
            # Add assistant response to session if using conversation manager
            if self.conversation_manager and session_id and full_response:
                await self.conversation_manager.add_message(
                    session_id,
                    full_response,
                    is_agent=True
                )
            
            # Complete the task
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            
            # Yield error status
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
            
            # Add error as artifact
            yield TaskArtifactUpdateEvent(
                id=task_id,
                artifact=Artifact(
                    name=f"{self.agent.name}_error",
                    parts=[TextPart(type="text", text=f"Error: {str(e)}")],
                    index=0
                )
            )