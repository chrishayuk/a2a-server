# File: a2a_server/tasks/handlers/adk/google_adk_handler.py
"""
Google ADK Agent Handler for A2A framework.

This handler provides integration with Google Agent Development Kit (ADK) agents,
allowing them to be used within the A2A task framework. The handler supports
optional session tracking for maintaining conversation context.
"""

import json
import logging
import asyncio
from typing import Any, AsyncIterable, Optional, List, Dict

from a2a_json_rpc.spec import (
    Message,
    TaskStatus,
    TaskState,
    Artifact,
    TextPart,
    DataPart,
    Role,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent
)

from a2a_server.tasks.task_handler import TaskHandler
from a2a_server.tasks.handlers.adk.adk_agent_adapter import ADKAgentAdapter
from a2a_server.tasks.handlers.adk.google_adk_protocol import GoogleADKAgentProtocol

# Check if session handling is available
try:
    from a2a_server.tasks.session_aware_task_handler import SESSIONS_AVAILABLE
    from a2a_server.tasks.handlers.adk.session_enabled_adk_handler import SessionEnabledADKHandler
except ImportError:
    SESSIONS_AVAILABLE = False

logger = logging.getLogger(__name__)


def _attach_raw_attributes(parts: List[Any]) -> None:
    """
    Attach raw attributes to Part wrappers so that attributes like .type, .data, .text
    can be accessed directly in tests.
    """
    for part in parts:
        pd = part.model_dump(exclude_none=True)
        for key, val in pd.items():
            try:
                object.__setattr__(part, key, val)
            except Exception:
                setattr(part, key, val)


class GoogleADKHandler(TaskHandler):
    """
    Task handler for Google ADK agents with optional session support.
    
    When use_sessions=True and chuk-session-manager is available, maintains
    conversation history and provides context to the agent.
    """
    abstract = True  # Exclude from automatic discovery; must be instantiated explicitly

    def __init__(
        self, 
        agent: GoogleADKAgentProtocol, 
        name: str = "google_adk",
        use_sessions: bool = False,
        token_threshold: int = 4000,
        summarization_strategy: str = "key_points",
        session_store = None
    ):
        """
        Initialize the Google ADK handler.
        
        Args:
            agent: The Google ADK agent
            name: Handler name
            use_sessions: Whether to enable session support
            token_threshold: Maximum tokens before summarization
            summarization_strategy: Strategy for summarizing conversations
            session_store: Optional session store to use
        """
        # Validate agent and wrap if needed
        if not (callable(getattr(agent, "invoke", None)) and callable(getattr(agent, "stream", None))):
            agent = ADKAgentAdapter(agent)
        
        self._agent = agent
        self._name = name
        self._supported_types = getattr(agent, "SUPPORTED_CONTENT_TYPES", ["text/plain"])
        
        # Check if we should use sessions
        self._use_sessions = use_sessions and SESSIONS_AVAILABLE
        
        # Initialize session support if requested and available
        if self._use_sessions:
            try:
                # Create a SessionEnabledADKHandler for session support
                self._session_handler = SessionEnabledADKHandler(
                    agent=agent, 
                    name=name,
                    session_store=session_store,
                    token_threshold=token_threshold,
                    summarization_strategy=summarization_strategy
                )
                logger.info(f"Initialized {name} Google ADK handler with session support")
            except ImportError:
                logger.warning(f"Session support requested for {name} but chuk-session-manager not installed")
                self._use_sessions = False
                
        if not self._use_sessions:
            logger.debug(f"Initialized {name} Google ADK handler in stateless mode")

    @property
    def name(self) -> str:
        """Get the handler name."""
        return self._name

    @property
    def supported_content_types(self) -> list[str]:
        """Get supported content types."""
        return self._supported_types

    def _extract_text_query(self, message: Message) -> str:
        """
        Extract text content from the message.
        
        Args:
            message: The message to extract text from
            
        Returns:
            The extracted text
            
        Raises:
            ValueError: If no text parts found
        """
        for part in message.parts or []:
            data = part.model_dump(exclude_none=True)
            if data.get("type") == "text" and "text" in data:
                return data.get("text", "") or ""
        raise ValueError("Message does not contain any text parts")

    async def _handle_streaming_response(
        self,
        task_id: str,
        query: str,
        session_id: Optional[str]
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """
        Handle streaming response from the agent.
        
        Args:
            task_id: The task ID
            query: The user query
            session_id: Optional session ID
            
        Yields:
            Status and artifact events
        """
        # Initial working status
        logger.debug(f"Starting streaming response for task {task_id}")
        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=TaskState.working), final=False)
        
        try:
            async for item in self._agent.stream(query, session_id):
                if not item.get("is_task_complete", False):
                    continue

                logger.debug(f"Received completed task response for {task_id}")
                content = item.get("content", "")
                parts: List[Any] = []
                final_state = TaskState.completed

                if isinstance(content, dict):
                    if "response" in content and "result" in content["response"]:
                        try:
                            data = json.loads(content["response"]["result"])
                            parts.append(DataPart(type="data", data=data))
                            final_state = TaskState.input_required
                            logger.debug(f"Task {task_id} requires additional input")
                        except json.JSONDecodeError:
                            parts.append(TextPart(type="text", text=str(content["response"]["result"])))
                    else:
                        parts.append(DataPart(type="data", data=content))
                else:
                    parts.append(TextPart(type="text", text=str(content)))

                # Add to session if enabled
                if self._use_sessions and isinstance(content, str):
                    agent_session_id = self._session_handler._get_agent_session_id(session_id)
                    if agent_session_id:
                        await self._session_handler.add_to_session(agent_session_id, str(content), is_agent=True)

                artifact = Artifact(name="google_adk_result", parts=parts, index=0)
                _attach_raw_attributes(artifact.parts)
                yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
                yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=final_state), final=True)
                logger.debug(f"Task {task_id} completed with state {final_state}")
                return
        except ValueError as e:
            logger.debug(f"Value error in streaming for task {task_id} (will try sync): {e}")
            raise
        except Exception as e:
            logger.error(f"Error in Google ADK streaming: {e}")
            logger.debug("Full exception details:", exc_info=True)
            error_msg = f"Error processing request: {e}"
            error_message = Message(role=Role.agent, parts=[TextPart(type="text", text=error_msg)])
            _attach_raw_attributes(error_message.parts)
            status = TaskStatus(state=TaskState.failed)
            object.__setattr__(status, 'message', error_message)
            yield TaskStatusUpdateEvent(id=task_id, status=status, final=True)

    async def _handle_sync_response(
        self,
        task_id: str,
        query: str,
        session_id: Optional[str]
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """
        Handle synchronous response from the agent.
        
        Args:
            task_id: The task ID
            query: The user query
            session_id: Optional session ID
            
        Yields:
            Status and artifact events
        """
        # Working status
        logger.debug(f"Starting synchronous response for task {task_id}")
        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=TaskState.working), final=False)
        
        # Get context from session if available
        context = None
        agent_session_id = None
        if self._use_sessions and session_id:
            agent_session_id = self._session_handler._get_agent_session_id(session_id)
            if agent_session_id:
                context = await self._session_handler.get_context(agent_session_id)
        
        try:
            # If we have context from session history, create a combined prompt
            if context and len(context) > 1:
                context_message = "Previous conversation:\n"
                for i, msg in enumerate(context[:-1]):  # Skip the last message (current)
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    context_message += f"{role.upper()}: {content}\n\n"
                context_message += f"Current message: {query}"
                
                # Try to use session_id parameter if supported
                try:
                    result = await asyncio.to_thread(self._agent.invoke, query, session_id=session_id)
                except TypeError:
                    # If that fails, use the context message instead
                    result = await asyncio.to_thread(self._agent.invoke, context_message)
            else:
                # No context, just invoke with query
                result = await asyncio.to_thread(self._agent.invoke, query, session_id=session_id)
                
            logger.debug(f"Received synchronous response for task {task_id}")
            
            # Add to session if enabled
            if self._use_sessions and agent_session_id:
                await self._session_handler.add_to_session(agent_session_id, result, is_agent=True)
        except Exception as e:
            logger.error(f"Error in Google ADK invocation: {e}")
            logger.debug("Full exception details:", exc_info=True)
            error_msg = f"Error processing request: {e}"
            error_message = Message(role=Role.agent, parts=[TextPart(type="text", text=error_msg)])
            _attach_raw_attributes(error_message.parts)
            status = TaskStatus(state=TaskState.failed)
            object.__setattr__(status, 'message', error_message)
            yield TaskStatusUpdateEvent(id=task_id, status=status, final=True)
            return

        is_input = "MISSING_INFO:" in result
        final_state = TaskState.input_required if is_input else TaskState.completed
        parts: List[Any] = [TextPart(type="text", text=result)]
        artifact = Artifact(name="google_adk_result", parts=parts, index=0)
        _attach_raw_attributes(artifact.parts)
        yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=final_state), final=True)
        logger.debug(f"Task {task_id} completed with state {final_state}")

    async def process_task(
        self,
        task_id: str,
        message: Message,
        session_id: Optional[str] = None
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """
        Process a task with the Google ADK agent.
        
        Args:
            task_id: The task ID
            message: The user message
            session_id: Optional session ID
            
        Yields:
            Status and artifact events
        """
        logger.debug(f"Processing task {task_id} with session {session_id or 'new'}")
        query = self._extract_text_query(message)
        
        # Add user message to session if enabled
        if self._use_sessions and session_id:
            agent_session_id = self._session_handler._get_agent_session_id(session_id)
            if agent_session_id:
                await self._session_handler.add_to_session(agent_session_id, query, is_agent=False)

        # Use streaming if available
        use_stream = callable(getattr(self._agent, 'stream', None)) \
                     and not type(self._agent).__module__.startswith('google.adk')

        if use_stream:
            logger.debug(f"Using streaming mode for task {task_id}")
            try:
                async for event in self._handle_streaming_response(task_id, query, session_id):
                    yield event
                return
            except ValueError:
                logger.debug(f"Streaming failed for task {task_id}, falling back to synchronous invocation")
        else:
            logger.debug(f"Using synchronous mode for task {task_id}")

        async for event in self._handle_sync_response(task_id, query, session_id):
            yield event

    async def cancel_task(self, task_id: str) -> bool:
        """
        Attempt to cancel a running task (not supported by Google ADK).
        
        Args:
            task_id: The task ID to cancel
            
        Returns:
            Always False (not supported)
        """
        logger.debug(f"Cancellation request for task {task_id} - not supported by Google ADK agent")
        return False
    
    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get conversation history for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            List of messages in ChatML format, or empty list if sessions disabled
        """
        if self._use_sessions:
            return await self._session_handler.get_conversation_history(session_id)
        return []
    
    async def get_token_usage(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get token usage statistics for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            Dictionary with token usage statistics, or empty stats if sessions disabled
        """
        if self._use_sessions:
            return await self._session_handler.get_token_usage(session_id)
        return {"total_tokens": 0, "total_cost": 0}