# a2a_server/tasks/handlers/resilient_handler.py
"""
Simplified Universal Handler with proper ADK integration and cross-agent session support.
"""
import asyncio
import logging
import time
from typing import AsyncGenerator, Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass

from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, TaskStatusUpdateEvent, 
    TaskArtifactUpdateEvent, Artifact, TextPart, Role
)

logger = logging.getLogger(__name__)


class HandlerState(Enum):
    """States for the handler."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class HandlerHealth:
    """Health tracking for the handler."""
    state: HandlerState = HandlerState.HEALTHY
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    last_success: Optional[float] = None
    last_failure: Optional[float] = None
    last_error: Optional[str] = None


class ResilientHandler(SessionAwareTaskHandler):
    """
    Simplified universal handler with proper ADK integration and cross-agent session support.
    No circuit breaking or background tasks - just simple retry logic.
    """
    
    def __init__(
        self, 
        agent,  # Any agent type
        name: Optional[str] = None,
        task_timeout: float = 300.0,
        max_retry_attempts: int = 2,
        # Session support
        sandbox_id: Optional[str] = None,
        infinite_context: bool = True,
        token_threshold: int = 4000,
        max_turns_per_segment: int = 50,
        default_ttl_hours: int = 24,
        session_store=None,
        # Session sharing parameters
        session_sharing: Optional[bool] = None,
        shared_sandbox_group: Optional[str] = None,
        **kwargs
    ):
        """Initialize the resilient handler with ADK support and session sharing."""
        self.agent = self._load_agent(agent)
        detected_name = name or self._detect_agent_name()
        
        # Store session sharing configuration
        self.session_sharing = session_sharing
        self.shared_sandbox_group = shared_sandbox_group
        
        # Auto-configure session sharing if not explicitly set
        if self.shared_sandbox_group:
            # Force session sharing to True when shared_sandbox_group is provided
            self.session_sharing = True
            effective_sandbox_id = self.shared_sandbox_group
            logger.debug(f"Session sharing enabled: using shared sandbox '{effective_sandbox_id}' instead of '{sandbox_id}'")
        else:
            # Use provided sandbox_id or generate default
            self.session_sharing = session_sharing if session_sharing is not None else False
            effective_sandbox_id = sandbox_id or f"a2a-handler-{detected_name}"
        
        # Initialize base SessionAwareTaskHandler with effective sandbox and session sharing
        super().__init__(
            name=detected_name,
            sandbox_id=effective_sandbox_id,
            infinite_context=infinite_context,
            token_threshold=token_threshold,
            max_turns_per_segment=max_turns_per_segment,
            default_ttl_hours=default_ttl_hours,
            session_store=session_store,
            session_sharing=self.session_sharing,
            shared_sandbox_group=self.shared_sandbox_group,
            **kwargs
        )
        
        # Simple configuration
        self.task_timeout = task_timeout
        self.max_retry_attempts = max_retry_attempts
        
        # Health tracking
        self.health = HandlerHealth()
        
        # Agent interface detection
        self._agent_interface = self._detect_agent_interface()
        
        if self.agent is None:
            logger.error(f"Failed to load agent for handler '{self._name}'")
            self.health.state = HandlerState.FAILED
        else:
            session_type = "SHARED" if self.session_sharing else "ISOLATED"
            session_info = f"group: {self.shared_sandbox_group}" if self.session_sharing else f"sandbox: {self.sandbox_id}"
            
            logger.debug(f"Initialized handler '{self._name}' with {self._agent_interface} interface and {session_type} sessions ({session_info})")
    
    def _load_agent(self, agent_spec):
        """Load agent from specification."""
        if agent_spec is None:
            logger.error("Agent specification is None")
            return None
        
        # If already an instance (has attributes but isn't callable), use directly
        if (hasattr(agent_spec, '__class__') and 
            not callable(agent_spec) and 
            (hasattr(agent_spec, 'name') or hasattr(agent_spec, 'process_task') or hasattr(agent_spec, 'invoke'))):
            logger.debug(f"Using agent instance directly: {type(agent_spec)}")
            return agent_spec
        
        # If it's a callable (factory function), DON'T call it here
        # Let the subclass handle it with proper parameters
        if callable(agent_spec):
            logger.debug(f"Agent is callable (factory function): {agent_spec}")
            logger.debug(f"Will be processed by subclass with YAML parameters")
            return agent_spec
        
        # If string, try to import
        if isinstance(agent_spec, str):
            try:
                import importlib
                module_path, _, attr = agent_spec.rpartition('.')
                module = importlib.import_module(module_path)
                agent_instance = getattr(module, attr)
                logger.debug(f"Imported agent from string: {agent_spec}")
                return agent_instance
            except (ImportError, AttributeError) as e:
                logger.error(f"Failed to import agent from '{agent_spec}': {e}")
                return None
        
        logger.error(f"Unknown agent specification type: {type(agent_spec)}")
        return None
    
    def _detect_agent_name(self) -> str:
        """Detect agent name from the agent instance."""
        if self.agent is None:
            return "unknown_agent"
        
        # If agent is a callable (factory function), try to get name from function
        if callable(self.agent):
            func_name = getattr(self.agent, '__name__', 'unknown_function')
            if func_name.startswith('create_'):
                return func_name.replace('create_', '').replace('_agent', '')
            return func_name.replace('_', '')
            
        if hasattr(self.agent, 'name'):
            return str(self.agent.name)
        elif hasattr(self.agent, '__class__'):
            class_name = self.agent.__class__.__name__.lower()
            # Clean up common suffixes
            for suffix in ['agent', 'handler', 'client']:
                if class_name.endswith(suffix):
                    class_name = class_name[:-len(suffix)]
                    break
            return class_name or "unknown_agent"
        else:
            return "unknown_agent"
    
    def _detect_agent_interface(self) -> str:
        """Detect which interface the agent supports."""
        if self.agent is None:
            logger.error("Cannot detect interface - agent is None")
            return "unknown"
        
        # If agent is a callable (factory function), we can't detect interface yet
        if callable(self.agent):
            logger.debug(f"Agent is callable (factory function) - interface will be detected after instantiation")
            return "function"
        
        # Check for each interface in order of preference
        interfaces_to_check = [
            ('process_task', 'process_task'),
            ('process_message', 'process_message'), 
            ('complete', 'complete'),
            ('chat', 'chat'),
            ('invoke', 'invoke'),
            ('run_async', 'adk_async'),
            ('run_live', 'adk_live'),
        ]
        
        for method_name, interface_name in interfaces_to_check:
            try:
                if hasattr(self.agent, method_name):
                    method = getattr(self.agent, method_name)
                    if callable(method):
                        logger.debug(f"Detected {interface_name} interface for agent {self._detect_agent_name()}")
                        return interface_name
            except Exception as e:
                logger.debug(f"Error checking for {method_name}: {e}")
        
        # Special check for ADK agents
        if self._is_adk_agent(self.agent):
            logger.debug(f"Detected ADK agent type for {self._detect_agent_name()}")
            return "adk_agent"
        
        logger.error(f"Could not detect interface for agent {self._detect_agent_name()}")
        return "unknown"
    
    def _is_adk_agent(self, agent) -> bool:
        """Check if this is an ADK agent by examining its class hierarchy."""
        try:
            if callable(agent):
                return False
                
            class_name = agent.__class__.__name__
            module_name = agent.__class__.__module__
            
            adk_indicators = [
                'LlmAgent', 'Agent',
                'google.adk', 'adk.',
            ]
            
            for indicator in adk_indicators:
                if indicator in class_name or indicator in module_name:
                    return True
                    
            # Check for ADK-specific attributes
            adk_attributes = ['run_async', 'run_live', 'model', 'instruction']
            has_adk_attrs = sum(1 for attr in adk_attributes if hasattr(agent, attr))
            
            return has_adk_attrs >= 3
            
        except Exception:
            return False
    
    @property
    def supported_content_types(self) -> List[str]:
        """Get supported content types."""
        if callable(self.agent):
            return ["text/plain", "multipart/mixed"]
            
        if hasattr(self.agent, 'supported_content_types'):
            return self.agent.supported_content_types
        elif hasattr(self.agent, 'SUPPORTED_CONTENT_TYPES'):
            return self.agent.SUPPORTED_CONTENT_TYPES
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
    
    async def _process_with_retry(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Process task with simple retry logic."""
        
        # Track this task
        self.health.total_tasks += 1
        
        # Add user message to session
        user_content = self._extract_message_content(message)
        await self.add_user_message(session_id, user_content)
        
        for attempt in range(self.max_retry_attempts + 1):
            try:
                # Yield working status on first attempt
                if attempt == 0:
                    yield TaskStatusUpdateEvent(
                        id=task_id,
                        status=TaskStatus(state=TaskState.working),
                        final=False
                    )
                elif attempt > 0:
                    logger.debug(f"Retrying task {task_id} for {self._name} (attempt {attempt + 1})")
                
                # Process with timeout
                async with asyncio.timeout(self.task_timeout):
                    response_content = None
                    async for event in self._delegate_to_agent(task_id, message, session_id):
                        # Capture response content for session tracking
                        if isinstance(event, TaskArtifactUpdateEvent):
                            if hasattr(event.artifact, 'parts') and event.artifact.parts:
                                for part in event.artifact.parts:
                                    if hasattr(part, 'text') and part.text:
                                        response_content = part.text
                                        break
                        yield event
                    
                    # Add AI response to session
                    if response_content and session_id:
                        await self.add_ai_response(session_id, response_content)
                
                # If we get here, task succeeded
                self._record_task_success()
                return
                
            except asyncio.TimeoutError:
                error_msg = f"Task timed out after {self.task_timeout}s"
                logger.warning(f"Task {task_id} {error_msg} (attempt {attempt + 1})")
                
                if attempt < self.max_retry_attempts:
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    self._record_task_failure(error_msg)
                    yield TaskStatusUpdateEvent(
                        id=task_id,
                        status=TaskStatus(
                            state=TaskState.failed,
                            message=None
                        ),
                        final=True
                    )
                    return
                    
            except Exception as e:
                error_msg = f"Task failed: {str(e)}"
                logger.error(f"Task {task_id} failed for {self._name} (attempt {attempt + 1}): {e}")
                
                if attempt < self.max_retry_attempts:
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    self._record_task_failure(error_msg)
                    yield TaskStatusUpdateEvent(
                        id=task_id,
                        status=TaskStatus(
                            state=TaskState.failed,
                            message=None
                        ),
                        final=True
                    )
                    return
    
    async def _delegate_to_agent(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Delegate task processing to the appropriate agent interface."""
        
        # Handle callable agents (should not happen in ResilientHandler)
        if callable(self.agent):
            logger.error(f"Agent is still callable - this should have been handled by subclass!")
            raise RuntimeError(f"Agent {self._name} is still a callable function - parameter processing failed")
        
        if self._agent_interface == "process_task":
            async for event in self.agent.process_task(task_id, message, session_id):
                yield event
                
        elif self._agent_interface == "process_message":
            async for event in self.agent.process_message(task_id, message, session_id):
                yield event
                
        elif self._agent_interface == "complete":
            async for event in self._adapt_complete_agent(task_id, message, session_id):
                yield event
                
        elif self._agent_interface == "chat":
            async for event in self._adapt_chat_agent(task_id, message, session_id):
                yield event
                
        elif self._agent_interface == "invoke":
            async for event in self._adapt_invoke_agent(task_id, message, session_id):
                yield event
                
        elif self._agent_interface in ["adk_async", "adk_live", "adk_agent"]:
            async for event in self._adapt_adk_agent(task_id, message, session_id):
                yield event
                
        elif self._agent_interface == "function":
            logger.error(f"Agent is still a function - this indicates parameter processing failed")
            raise RuntimeError(f"Agent {self._name} was not properly instantiated from factory function")
            
        else:
            raise RuntimeError(f"Agent {self._name} has unsupported interface: {self._agent_interface}")
    
    async def _adapt_complete_agent(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Adapt an agent with complete method to the TaskHandler interface."""
        try:
            user_content = self._extract_message_content(message)
            
            # Initialize tools if available
            if hasattr(self.agent, 'initialize_tools'):
                await self.agent.initialize_tools()
            
            # Get conversation context from handler's session management
            context_messages = await self.get_conversation_context(session_id, max_messages=20)
            logger.debug(f"Retrieved {len(context_messages)} context messages from external storage")
            
            # Build messages for completion
            messages = []
            
            # Add system prompt
            system_prompt = ""
            if hasattr(self.agent, 'get_system_prompt'):
                system_prompt = self.agent.get_system_prompt()
            elif hasattr(self.agent, 'instruction'):
                system_prompt = self.agent.instruction
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            # Add conversation context
            messages.extend(context_messages)
            
            # Add current message
            messages.append({"role": "user", "content": user_content})
            
            # Use complete method
            result = await self.agent.complete(messages, use_tools=True, session_id=session_id)
            
            # Convert result to A2A artifacts
            content = result.get("content", "No response generated")
            
            # Emit tool artifacts if tools were used
            if result.get("tool_calls"):
                for i, (tool_call, tool_result) in enumerate(zip(result["tool_calls"], result.get("tool_results", []))):
                    tool_name = tool_call.get("function", {}).get("name", "unknown")
                    tool_content = tool_result.get("content", "No result")
                    
                    tool_artifact = Artifact(
                        name=f"tool_call_{i}",
                        parts=[TextPart(type="text", text=f"🔧 {tool_name}: {tool_content}")],
                        index=i + 1
                    )
                    yield TaskArtifactUpdateEvent(id=task_id, artifact=tool_artifact)
            
            # Emit final response
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=content)],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=response_artifact)
            
            # Success
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error adapting complete agent {self._name}: {e}")
            raise
    
    async def _adapt_chat_agent(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Adapt a simple chat agent to the TaskHandler interface."""
        try:
            user_content = self._extract_message_content(message)
            result = await self.agent.chat(user_content, session_id=session_id)
            
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=result)],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=response_artifact)
            
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error adapting chat agent {self._name}: {e}")
            raise
    
    async def _adapt_invoke_agent(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Adapt an agent with invoke method to the TaskHandler interface."""
        try:
            user_content = self._extract_message_content(message)
            result = await asyncio.to_thread(self.agent.invoke, user_content, session_id=session_id)
            
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=result)],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=response_artifact)
            
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error adapting invoke agent {self._name}: {e}")
            raise
    
    async def _adapt_adk_agent(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Adapt an ADK agent to the TaskHandler interface."""
        try:
            user_content = self._extract_message_content(message)
            
            result = None
            
            # Method 1: Use ADK adapter if available
            if hasattr(self.agent, 'invoke'):
                try:
                    result = await asyncio.to_thread(self.agent.invoke, user_content, session_id)
                except Exception as e:
                    logger.debug(f"ADK invoke failed: {e}")
            
            # Method 2: Use run_async
            if result is None and hasattr(self.agent, 'run_async'):
                try:
                    from google.genai import types
                    
                    content_obj = types.Content(
                        role="user", 
                        parts=[types.Part.from_text(text=user_content)]
                    )
                    
                    events = []
                    async for event in self.agent.run_async(
                        user_id="a2a_user",
                        session_id=session_id or "default",
                        new_message=content_obj
                    ):
                        events.append(event)
                    
                    if events and events[-1].content and events[-1].content.parts:
                        result = "".join(
                            p.text for p in events[-1].content.parts 
                            if getattr(p, "text", None)
                        )
                    
                except Exception as e:
                    logger.debug(f"ADK run_async failed: {e}")
            
            # Fallback
            if result is None:
                result = "I apologize, but I'm having trouble processing your request right now."
            
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=result or "No response generated")],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=response_artifact)
            
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error adapting ADK agent {self._name}: {e}")
            raise
    
    def _record_task_success(self):
        """Record a successful task completion."""
        self.health.successful_tasks += 1
        self.health.last_success = time.time()
        
        if self.health.state == HandlerState.DEGRADED:
            self.health.state = HandlerState.HEALTHY
            logger.debug(f"Handler {self._name} recovered")
    
    def _record_task_failure(self, error: str):
        """Record a failed task."""
        self.health.failed_tasks += 1
        self.health.last_failure = time.time()
        self.health.last_error = error
        self.health.state = HandlerState.DEGRADED
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator:
        """Process a task with simple retry logic."""
        if self.agent is None:
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(
                    state=TaskState.failed,
                    message=None
                ),
                final=True
            )
            return
        
        async for event in self._process_with_retry(task_id, message, session_id):
            yield event
    
    async def cancel_task(self, task_id: str) -> bool:
        """Attempt to cancel a running task."""
        if self.agent and hasattr(self.agent, 'cancel_task'):
            try:
                return await self.agent.cancel_task(task_id)
            except Exception as e:
                logger.error(f"Error cancelling task {task_id} for {self._name}: {e}")
                return False
        return False
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        agent_health = {}
        if self.agent and hasattr(self.agent, 'get_health_status'):
            try:
                agent_health = self.agent.get_health_status()
            except Exception as e:
                agent_health = {"error": str(e)}
        
        session_stats = self.get_session_stats()
        
        return {
            "handler_name": self._name,
            "handler_state": self.health.state.value,
            "agent_interface": self._agent_interface,
            "session_sharing": getattr(self, 'session_sharing', False),
            "shared_sandbox_group": getattr(self, 'shared_sandbox_group', None),
            "task_stats": {
                "total_tasks": self.health.total_tasks,
                "successful_tasks": self.health.successful_tasks,
                "failed_tasks": self.health.failed_tasks,
                "success_rate": self.health.successful_tasks / max(self.health.total_tasks, 1),
                "last_success": self.health.last_success,
                "last_failure": self.health.last_failure
            },
            "session_stats": session_stats,
            "agent_health": agent_health,
            "last_error": self.health.last_error
        }
    
    async def shutdown(self):
        """Cleanup resources."""
        if self.agent and hasattr(self.agent, 'shutdown'):
            try:
                await self.agent.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down agent for {self._name}: {e}")


# Export the resilient handler
__all__ = ["ResilientHandler"]