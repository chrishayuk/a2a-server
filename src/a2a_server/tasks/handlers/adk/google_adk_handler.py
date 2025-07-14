# a2a_server/tasks/handlers/adk/google_adk_handler.py
"""
Clean Google ADK Handler - Sessions Auto-Expire
-----------------------------------------------

Simplified version that relies on session auto-expiration rather than
complex lifecycle management that was causing duplicate task creation.
"""
import logging
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator

from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, TaskStatusUpdateEvent, 
    TaskArtifactUpdateEvent, Artifact, TextPart
)

logger = logging.getLogger(__name__)


class GoogleADKHandler(SessionAwareTaskHandler):
    """
    Clean Google ADK Handler with auto-expiring sessions.
    
    Relies on natural session expiration rather than complex lifecycle
    management to prevent duplicate task creation issues.
    """
    
    def __init__(
        self,
        agent,  # ADK agent or adapter
        name: Optional[str] = None,
        task_timeout: float = 240.0,
        # Simple session parameters
        sandbox_id: Optional[str] = None,
        session_sharing: Optional[bool] = None,
        shared_sandbox_group: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize Google ADK handler with clean session handling.
        
        Args:
            agent: Google ADK agent instance (raw or wrapped)
            name: Handler name (auto-detected if None)
            task_timeout: Max time per task (default: 240s)
            sandbox_id: Session sandbox ID
            session_sharing: Whether to enable session sharing
            shared_sandbox_group: Group for shared sessions
            **kwargs: Additional arguments passed to SessionAwareTaskHandler
        """
        # Wrap the agent if needed
        self.agent = self._wrap_adk_agent(agent)
        self.task_timeout = task_timeout
        
        # Detect name
        detected_name = name or self._detect_agent_name()
        
        # Simple session configuration
        effective_sandbox = sandbox_id or f"adk-{detected_name}"
        if shared_sandbox_group:
            session_sharing = True
            effective_sandbox = shared_sandbox_group
        
        # Initialize with session support
        super().__init__(
            name=detected_name,
            sandbox_id=effective_sandbox,
            session_sharing=session_sharing,
            shared_sandbox_group=shared_sandbox_group,
            **kwargs
        )
        
        session_type = "SHARED" if self.session_sharing else "ISOLATED"
        logger.debug(f"Initialized GoogleADKHandler '{self.name}' with {session_type} sessions (CLEAN - auto-expire)")
    
    def _wrap_adk_agent(self, agent):
        """Wrap ADK agent with adapter if needed."""
        # If it already has invoke method, use it
        if hasattr(agent, 'invoke'):
            logger.debug(f"Agent already has invoke method: {type(agent)}")
            return agent
        
        # Check if it's a raw Google ADK Agent that needs wrapping
        if self._is_raw_adk_agent(agent):
            try:
                from a2a_server.tasks.handlers.adk.adk_agent_adapter import ADKAgentAdapter
                wrapped = ADKAgentAdapter(agent)
                logger.debug(f"Wrapped raw ADK agent: {type(agent)} -> ADKAgentAdapter")
                return wrapped
            except ImportError as e:
                logger.error(f"Could not import ADKAgentAdapter: {e}")
                return agent
            except Exception as e:
                logger.error(f"Failed to wrap ADK agent: {e}")
                return agent
        
        # Use agent directly
        logger.warning(f"Using agent directly without wrapping: {type(agent)}")
        return agent
    
    def _is_raw_adk_agent(self, agent) -> bool:
        """Check if this is a raw Google ADK Agent."""
        try:
            class_name = agent.__class__.__name__
            module_name = agent.__class__.__module__
            
            # Handle special mock cases where __module__ is overridden as a property
            if hasattr(agent, '__module__') and isinstance(getattr(type(agent), '__module__', None), property):
                module_name = agent.__module__
            
            # Look for ADK indicators - must be from google.adk module
            is_adk_module = 'google.adk' in module_name
            
            # Check for ADK attributes
            has_adk_attrs = (
                hasattr(agent, 'name') and 
                hasattr(agent, 'model') and 
                hasattr(agent, 'instruction')
            )
            
            # Must be from google.adk module AND have ADK attributes AND lack invoke method
            return is_adk_module and has_adk_attrs and not hasattr(agent, 'invoke')
            
        except Exception:
            return False
    
    def _detect_agent_name(self) -> str:
        """Detect agent name."""
        if hasattr(self.agent, 'name'):
            return str(self.agent.name).replace(' ', '_').lower()
        elif hasattr(self.agent, '__class__'):
            class_name = self.agent.__class__.__name__.lower()
            # Remove common suffixes
            for suffix in ['agent', 'handler', 'client']:
                if class_name.endswith(suffix):
                    class_name = class_name[:-len(suffix)]
                    break
            return class_name or "google_adk"
        else:
            return "google_adk"
    
    def _extract_message_content(self, message: Message) -> str:
        """Extract text content from A2A message."""
        if not message or not hasattr(message, 'parts') or not message.parts:
            return ""
            
        text_parts = []
        for part in message.parts:
            try:
                # Try direct text attribute first
                if hasattr(part, "text") and part.text:
                    text_parts.append(str(part.text))
                # Try model_dump if available
                elif hasattr(part, "model_dump"):
                    part_dict = part.model_dump()
                    if "text" in part_dict and part_dict["text"]:
                        text_parts.append(str(part_dict["text"]))
                # Try dict-like access
                elif hasattr(part, '__getitem__'):
                    try:
                        text = part["text"]
                        if text:
                            text_parts.append(str(text))
                    except (KeyError, TypeError):
                        pass
            except Exception as e:
                logger.debug(f"Error extracting text from part {type(part)}: {e}")
                continue
                
        result = " ".join(text_parts).strip()
        logger.debug(f"Extracted message content: '{result}' from {len(message.parts)} parts")
        return result
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator[TaskStatusUpdateEvent | TaskArtifactUpdateEvent, None]:
        """
        Process a task with the ADK agent using clean session handling.
        """
        
        logger.debug(f"Processing task {task_id[:8]}... with handler '{self.name}'")
        
        # Working status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        # Extract user content
        user_content = self._extract_message_content(message)
        if not user_content.strip():
            logger.warning(f"Empty message content for task {task_id}")
            user_content = "Hello"
        
        # Add user message to session (sessions auto-expire, no manual cleanup needed)
        if session_id and user_content:
            await self.add_user_message(session_id, user_content)
        
        try:
            # Direct synchronous call to agent
            result = self.agent.invoke(user_content, session_id)
            
            # Add AI response to session (auto-expires naturally)
            if session_id and result:
                await self.add_ai_response(session_id, result)
            
            # Emit response artifact
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=result or "No response")],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=response_artifact)
            
            # Success
            logger.info(f"Task {task_id[:8]}... completed successfully")
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            error_msg = f"Task failed: {str(e)}"
            logger.error(f"Task {task_id[:8]}... {error_msg}")
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        base_health = super().get_health_status()
        
        # Add ADK-specific info
        base_health.update({
            "handler_type": "google_adk",
            "agent_type": type(self.agent).__name__,
            "has_invoke": hasattr(self.agent, 'invoke'),
            "has_stream": hasattr(self.agent, 'stream'),
            "task_timeout": self.task_timeout,
            "session_lifecycle": "auto_expire_no_manual_cleanup",
        })
        
        return base_health


# Export class
__all__ = ["GoogleADKHandler"]