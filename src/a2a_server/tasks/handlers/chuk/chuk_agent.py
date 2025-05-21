"""
ChukAgent: A high-level agent abstraction using chuk-llm for a2a server integration,
with advanced session management powered by chuk_session_manager.
"""
import asyncio
import json
import logging
import re
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
    A high-level agent abstraction using chuk-llm for a2a server integration,
    with advanced session management powered by chuk_session_manager.
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        instruction: str = "",
        provider: str = "openai",
        model: Optional[str] = None,
        streaming: bool = True,
        config: Optional[ProviderConfig] = None,
        token_threshold: int = 4000,
        summarization_strategy: str = "key_points",
        enable_memory: bool = True
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
            token_threshold: Maximum tokens before session segmentation
            summarization_strategy: Strategy for summarizing sessions
            enable_memory: Whether to enable conversation memory
        """
        self.name = name
        self.description = description
        
        # Define a memory-focused instruction if none is provided
        default_instruction = f"""
You are a helpful culinary assistant specialized in suggesting recipes and providing cooking advice.

CRITICAL IDENTITY GUIDANCE:
1. If the user says "my name is X" or introduces themselves, ALWAYS acknowledge their name in your next response.
2. If the user asks "what's my name?", check your conversation memory and tell them what name they told you.
3. Address the user by name whenever possible in your responses.
4. Remember personal preferences they share.

Your primary goal is to help with cooking advice while creating a personalized experience.
"""
        
        # Enhance instruction with memory guidance if memory is enabled
        if enable_memory:
            if instruction:
                memory_instruction = """
IMPORTANT: You must remember personal information shared by the user.
When the user says their name, remember it and use it in future responses.
If they ever ask "what's my name?", tell them their name based on what they've told you earlier.
Similarly, remember and refer to other personal details they share like preferences, locations, etc.

This is critical for providing a personalized experience.
"""
                self.instruction = f"{instruction}\n\n{memory_instruction}"
            else:
                self.instruction = default_instruction
        else:
            self.instruction = instruction or default_instruction
        
        self.provider = provider
        self.model = model
        self.streaming = streaming
        self.config = config or ProviderConfig()
        self.token_threshold = token_threshold
        self.summarization_strategy = summarization_strategy
        self.enable_memory = enable_memory
        
        # Session tracking
        self.session_map = {}  # Map a2a session IDs to chuk-session-manager session IDs
        self.session_failures = 0  # Track session failures for graceful degradation
        self.max_session_failures = 5  # Max failures before disabling session management
        
        # Cache for user names
        self.user_names = {}  # Map session IDs to user names
        
        # Import session manager components here to avoid loading them if not used
        try:
            from chuk_session_manager.storage import SessionStoreProvider, InMemorySessionStore
            from chuk_session_manager.infinite_conversation import (
                InfiniteConversationManager, SummarizationStrategy
            )
            
            # Ensure we have a session store
            if not SessionStoreProvider.get_store():
                SessionStoreProvider.set_store(InMemorySessionStore())
            
            # Map string strategy to enum
            strategy_map = {
                "basic": SummarizationStrategy.BASIC,
                "key_points": SummarizationStrategy.KEY_POINTS,
                "query_focused": SummarizationStrategy.QUERY_FOCUSED,
                "topic_based": SummarizationStrategy.TOPIC_BASED
            }
            
            # Create the conversation manager
            self.conversation_manager = InfiniteConversationManager(
                token_threshold=token_threshold,
                summarization_strategy=strategy_map.get(
                    summarization_strategy.lower(), 
                    SummarizationStrategy.KEY_POINTS
                )
            )
            
            self.session_manager_available = True
            logger.info(f"Initialized agent '{name}' with session manager support")
            
        except ImportError:
            logger.warning(f"chuk_session_manager not available - falling back to basic session handling")
            self.conversation_manager = None
            self.session_manager_available = False
            
        logger.info(f"Initialized agent '{name}' using {provider}/{model or 'default'}")
    
    async def _create_llm_summary(self, messages: List[Dict[str, Any]]) -> str:
        """
        Generate a summary of the conversation using the LLM.
        
        Args:
            messages: The conversation history to summarize
            
        Returns:
            A summary of the conversation
        """
        # Initialize LLM client
        client = get_llm_client(
            provider=self.provider,
            model=self.model,
            config=self.config
        )
        
        # Create a system prompt for summarization
        system_prompt = f"""
        Create a concise summary of the conversation below.
        Focus on key points and main topics of the discussion.
        Be sure to include any personal details the user has shared, such as their name, preferences, etc.
        Format your response as a brief paragraph.
        """
        
        # Prepare messages for the LLM
        summary_messages = [
            {"role": "system", "content": system_prompt},
        ]
        
        # Add relevant conversation messages
        for msg in messages:
            if msg["role"] != "system":
                summary_messages.append(msg)
        
        # Get the summary from the LLM
        try:
            response = await client.create_completion(
                messages=summary_messages,
                stream=False
            )
            summary = response.get("response", "No summary generated")
            return summary
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "Error generating summary"
    
    async def _get_or_create_session(self, a2a_session_id: str) -> str:
        """
        Get or create a session ID for the chuk-session-manager.
        
        Args:
            a2a_session_id: The session ID from a2a server
            
        Returns:
            A session ID for the chuk-session-manager
        """
        if not self.session_manager_available or not self.enable_memory:
            return None
            
        try:
            # Initialize imports
            from chuk_session_manager.models.session import Session
            from chuk_session_manager.storage import SessionStoreProvider
            
            # Get the session store
            store = SessionStoreProvider.get_store()
            
            # Create a new session if we haven't seen this ID before
            if a2a_session_id not in self.session_map:
                new_session = await Session.create()
                self.session_map[a2a_session_id] = new_session.id
                logger.info(f"Created new session {new_session.id} for a2a session {a2a_session_id}")
                return new_session.id
            
            # Get the existing session ID from our map
            chuk_session_id = self.session_map[a2a_session_id]
            
            # Retrieve the session from the store
            session = await store.get(chuk_session_id)
            if session:
                return chuk_session_id
            else:
                # If session not found, create a new one
                new_session = await Session.create()
                self.session_map[a2a_session_id] = new_session.id
                return new_session.id
                
        except Exception as e:
            self.session_failures += 1
            logger.error(f"Error in _get_or_create_session: {str(e)}")
            
            # Disable session management if too many failures
            if self.session_failures >= self.max_session_failures:
                logger.warning(f"Too many session failures ({self.session_failures}), disabling session management")
                self.session_manager_available = False
                return None
                
            # Fallback to creating a new session on error
            try:
                from chuk_session_manager.models.session import Session
                new_session = await Session.create()
                self.session_map[a2a_session_id] = new_session.id
                return new_session.id
            except Exception as inner_e:
                logger.error(f"Failed to create fallback session: {str(inner_e)}")
                return None
    
    def _extract_name_from_message(self, content: str) -> Optional[str]:
        """
        Extract a name from a message content if present.
        
        Args:
            content: The message content to parse
            
        Returns:
            The extracted name, or None if not found
        """
        if not content:
            return None
            
        # Common patterns for name introduction
        patterns = [
            r"(?i)my name is (\w+)",
            r"(?i)i['']m (\w+)",
            r"(?i)i am (\w+)",
            r"(?i)call me (\w+)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                name = match.group(1)
                return name
                
        return None
    
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
        
        # Check for name information in the message
        user_name = self._extract_name_from_message(user_content_str)
        if user_name and session_id:
            self.user_names[session_id] = user_name
        
        # Check if this is a "what's my name" question
        is_name_question = False
        if isinstance(user_content_str, str):
            user_content_lower = user_content_str.lower()
            if "what's my name" in user_content_lower or "what is my name" in user_content_lower:
                is_name_question = True
        
        # Initialize LLM client
        client = get_llm_client(
            provider=self.provider,
            model=self.model,
            config=self.config
        )
        
        # Track response state
        started_generating = False
        full_response = ""
        chuk_session_id = None
        
        try:
            # Format messages for the LLM
            llm_messages = [{"role": "system", "content": self.instruction}]
            
            # Use the session manager if available
            if self.session_manager_available and session_id and self.enable_memory:
                try:
                    # Get or create a session
                    chuk_session_id = await self._get_or_create_session(session_id)
                    
                    if chuk_session_id:
                        from chuk_session_manager.models.event_source import EventSource
                        from chuk_session_manager.models.event_type import EventType
                        from chuk_session_manager.models.session import SessionEvent
                        from chuk_session_manager.storage import SessionStoreProvider
                        
                        # Get the session store and session
                        store = SessionStoreProvider.get_store()
                        session = await store.get(chuk_session_id)
                        
                        if session:
                            # Add the user message to the session
                            await session.add_event_and_save(
                                SessionEvent(
                                    message=user_content_str,
                                    source=EventSource.USER,
                                    type=EventType.MESSAGE
                                )
                            )
                            
                            # Build context from the session
                            try:
                                context = await self.conversation_manager.build_context_for_llm(chuk_session_id)
                                
                                # Ensure system instruction is at the beginning
                                if not context or context[0].get("role") != "system":
                                    context.insert(0, {"role": "system", "content": self.instruction})
                                
                                # Add special handling for "what's my name" questions
                                if is_name_question:
                                    stored_name = self.user_names.get(session_id)
                                    if stored_name:
                                        # Insert a special reminder about the name
                                        context.insert(1, {
                                            "role": "system", 
                                            "content": f"The user's name is {stored_name}. They are asking about their name, so make sure to tell them their name is {stored_name}."
                                        })
                                
                                # If we know the user's name, add it to the context
                                elif user_name or self.user_names.get(session_id):
                                    name_to_use = user_name or self.user_names.get(session_id)
                                    # Insert a reminder about the user's name
                                    context.insert(1, {
                                        "role": "system",
                                        "content": f"The user's name is {name_to_use}. Remember to use their name in your response."
                                    })
                                
                                llm_messages = context
                            except Exception as ctx_err:
                                logger.error(f"Error building context: {ctx_err}")
                                # Fallback to basic context
                                llm_messages = [
                                    {"role": "system", "content": self.instruction},
                                    {"role": "user", "content": user_content_str}
                                ]
                        else:
                            llm_messages.append({"role": "user", "content": user_content_str})
                    else:
                        llm_messages.append({"role": "user", "content": user_content_str})
                except Exception as e:
                    # If there's an error with the session manager, fall back to basic mode
                    self.session_failures += 1
                    logger.error(f"Error using session manager: {e}")
                    
                    # Disable session management if too many failures
                    if self.session_failures >= self.max_session_failures:
                        logger.warning(f"Too many session failures ({self.session_failures}), disabling session management")
                        self.session_manager_available = False
                        
                    llm_messages.append({"role": "user", "content": user_content_str})
            else:
                # Basic formatting without session manager
                llm_messages.append({"role": "user", "content": user_content_str})
            
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
                full_response = text_response
                
                # Create response artifact
                yield TaskArtifactUpdateEvent(
                    id=task_id,
                    artifact=Artifact(
                        name=f"{self.name}_response",
                        parts=[TextPart(type="text", text=text_response or "")],
                        index=0
                    )
                )
            
            # Add assistant response to session history if using session manager
            if self.session_manager_available and session_id and chuk_session_id and full_response and self.enable_memory:
                try:
                    from chuk_session_manager.models.event_source import EventSource
                    from chuk_session_manager.models.event_type import EventType
                    from chuk_session_manager.models.session import SessionEvent
                    from chuk_session_manager.storage import SessionStoreProvider
                    
                    # Get the store and then the session
                    store = SessionStoreProvider.get_store()
                    session = await store.get(chuk_session_id)
                    
                    if session:
                        # Add the assistant response
                        await session.add_event_and_save(
                            SessionEvent(
                                message=full_response,
                                source=EventSource.LLM,
                                type=EventType.MESSAGE
                            )
                        )
                        logger.info(f"Successfully added assistant response to session {chuk_session_id}")
                    else:
                        logger.warning(f"Session {chuk_session_id} not found for updating response")
                except Exception as e:
                    self.session_failures += 1
                    logger.error(f"Error updating session with assistant response: {str(e)}")
                    
                    # Disable session management if too many failures
                    if self.session_failures >= self.max_session_failures:
                        logger.warning(f"Too many session failures ({self.session_failures}), disabling session management")
                        self.session_manager_available = False
            
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
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
            
            # Add error as artifact
            yield TaskArtifactUpdateEvent(
                id=task_id,
                artifact=Artifact(
                    name=f"{self.name}_error",
                    parts=[TextPart(type="text", text=f"Error: {str(e)}")],
                    index=0
                )
            )
    
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get the conversation history for a session.
        
        Args:
            session_id: The session ID to get history for
            
        Returns:
            A list of message dictionaries
        """
        if not self.session_manager_available or not session_id or not self.enable_memory:
            return []
        
        try:
            # Get the chuk-session-manager session ID
            chuk_session_id = self.session_map.get(session_id)
            if not chuk_session_id:
                return []
                
            # Get the full conversation history
            history = await self.conversation_manager.get_full_conversation_history(chuk_session_id)
            
            # Convert to ChatML format
            formatted_history = []
            for role, source, content in history:
                formatted_history.append({
                    "role": role,
                    "content": content
                })
            
            return formatted_history
        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            return []
    
    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get token usage statistics for a session.
        
        Args:
            session_id: The session ID to get usage for
            
        Returns:
            A dictionary with usage statistics
        """
        if not self.session_manager_available or not session_id or not self.enable_memory:
            return {"total_tokens": 0, "total_cost": 0}
        
        try:
            # Get the chuk-session-manager session ID
            chuk_session_id = self.session_map.get(session_id)
            if not chuk_session_id:
                return {"total_tokens": 0, "total_cost": 0}
            
            # Use the session store to get the session
            from chuk_session_manager.storage import SessionStoreProvider
            store = SessionStoreProvider.get_store()
            session = await store.get(chuk_session_id)
                
            if not session:
                return {"total_tokens": 0, "total_cost": 0}
            
            # Get usage statistics
            usage = {
                "total_tokens": session.total_tokens,
                "total_cost": session.total_cost,
                "by_model": {}
            }
            
            # Add model-specific usage
            for model, model_usage in session.token_summary.usage_by_model.items():
                usage["by_model"][model] = {
                    "prompt_tokens": model_usage.prompt_tokens,
                    "completion_tokens": model_usage.completion_tokens,
                    "total_tokens": model_usage.total_tokens,
                    "cost": model_usage.estimated_cost_usd
                }
            
            # Add source-specific usage
            source_usage = await session.get_token_usage_by_source()
            usage["by_source"] = {}
            for source, summary in source_usage.items():
                usage["by_source"][source] = {
                    "total_tokens": summary.total_tokens,
                    "cost": summary.total_estimated_cost_usd
                }
            
            return usage
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")
            return {"total_tokens": 0, "total_cost": 0}