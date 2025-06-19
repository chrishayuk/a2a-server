# a2a_server/tasks/handlers/resilient_handler.py
"""
Universal Resilient Handler with proper ADK integration and cross-agent session support.
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
    RECOVERING = "recovering"
    FAILED = "failed"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class HandlerHealth:
    """Health tracking for the handler."""
    state: HandlerState = HandlerState.HEALTHY
    consecutive_failures: int = 0
    total_tasks: int = 0
    successful_tasks: int = 0
    last_success: Optional[float] = None
    last_failure: Optional[float] = None
    recovery_attempts: int = 0
    last_recovery_attempt: Optional[float] = None
    circuit_opened_at: Optional[float] = None
    last_error: Optional[str] = None


class ResilientHandler(SessionAwareTaskHandler):
    """
    Universal resilient handler with proper ADK integration and cross-agent session support.
    """
    
    def __init__(
        self, 
        agent,  # Any agent type
        name: Optional[str] = None,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_timeout: float = 120.0,
        task_timeout: float = 300.0,
        max_retry_attempts: int = 2,
        recovery_check_interval: float = 180.0,
        # Session support
        sandbox_id: Optional[str] = None,
        infinite_context: bool = True,
        token_threshold: int = 4000,
        max_turns_per_segment: int = 50,
        default_ttl_hours: int = 24,
        session_store=None,
        # NEW: Session sharing parameters
        session_sharing: Optional[bool] = None,
        shared_sandbox_group: Optional[str] = None,
        **kwargs
    ):
        """Initialize the resilient handler with ADK support and session sharing."""
        self.agent = self._load_agent(agent)
        detected_name = name or self._detect_agent_name()
        
        # *** NEW: Store session sharing configuration ***
        self.session_sharing = session_sharing
        self.shared_sandbox_group = shared_sandbox_group
        
        # *** FIX: Auto-configure session sharing if not explicitly set ***
        # CRITICAL: Must set session_sharing BEFORE calling super().__init__
        if self.shared_sandbox_group:
            # Force session sharing to True when shared_sandbox_group is provided
            self.session_sharing = True
            effective_sandbox_id = self.shared_sandbox_group
            logger.info(f"Session sharing enabled: using shared sandbox '{effective_sandbox_id}' instead of '{sandbox_id}'")
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
        
        # Resilience configuration
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_timeout = circuit_breaker_timeout
        self.task_timeout = task_timeout
        self.max_retry_attempts = max_retry_attempts
        self.recovery_check_interval = recovery_check_interval
        
        # Health tracking
        self.health = HandlerHealth()
        
        # Background tasks
        self._recovery_task: Optional[asyncio.Task] = None
        self._recovery_in_progress = False
        
        # Agent interface detection
        self._agent_interface = self._detect_agent_interface()
        
        if self.agent is None:
            logger.error(f"Failed to load agent for handler '{self._name}'")
            self.health.state = HandlerState.FAILED
        else:
            session_type = "SHARED" if self.session_sharing else "ISOLATED"
            session_info = f"group: {self.shared_sandbox_group}" if self.session_sharing else f"sandbox: {self.sandbox_id}"
            
            logger.info(f"Initialized resilient handler '{self._name}' with {self._agent_interface} interface and {session_type} sessions ({session_info})")
            
            # Start recovery monitoring
            self._recovery_task = asyncio.create_task(self._recovery_monitor())
    
    def _load_agent(self, agent_spec):
        """Load agent from specification."""
        if agent_spec is None:
            logger.error("Agent specification is None")
            return None
        
        # If already an instance, use directly
        if hasattr(agent_spec, '__class__'):
            return agent_spec
        
        # If string, try to import
        if isinstance(agent_spec, str):
            try:
                import importlib
                module_path, _, attr = agent_spec.rpartition('.')
                module = importlib.import_module(module_path)
                agent_instance = getattr(module, attr)
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
        
        # Check for each interface in order of preference
        interfaces_to_check = [
            ('process_task', 'process_task'),
            ('process_message', 'process_message'), 
            ('complete', 'complete'),
            ('chat', 'chat'),
            ('invoke', 'invoke'),
            ('run_async', 'adk_async'),  # ADK async interface
            ('run_live', 'adk_live'),   # ADK live interface  
        ]
        
        for method_name, interface_name in interfaces_to_check:
            try:
                if hasattr(self.agent, method_name):
                    method = getattr(self.agent, method_name)
                    if callable(method):
                        logger.info(f"Detected {interface_name} interface for agent {self._detect_agent_name()}")
                        return interface_name
            except Exception as e:
                logger.debug(f"Error checking for {method_name}: {e}")
        
        # Special check for ADK agents - they might be wrapped
        if self._is_adk_agent(self.agent):
            logger.info(f"Detected ADK agent type for {self._detect_agent_name()}")
            return "adk_agent"
        
        logger.error(f"Could not detect interface for agent {self._detect_agent_name()}")
        return "unknown"
    
    def _is_adk_agent(self, agent) -> bool:
        """Check if this is an ADK agent by examining its class hierarchy."""
        try:
            # Check for ADK agent class names or modules
            class_name = agent.__class__.__name__
            module_name = agent.__class__.__module__
            
            adk_indicators = [
                'LlmAgent', 'Agent',  # Class names
                'google.adk', 'adk.',  # Module prefixes
            ]
            
            for indicator in adk_indicators:
                if indicator in class_name or indicator in module_name:
                    return True
                    
            # Check for ADK-specific attributes
            adk_attributes = ['run_async', 'run_live', 'model', 'instruction']
            has_adk_attrs = sum(1 for attr in adk_attributes if hasattr(agent, attr))
            
            # If it has most ADK attributes, it's likely an ADK agent
            return has_adk_attrs >= 3
            
        except Exception:
            return False
    
    @property
    def supported_content_types(self) -> List[str]:
        """Get supported content types."""
        if hasattr(self.agent, 'supported_content_types'):
            return self.agent.supported_content_types
        elif hasattr(self.agent, 'SUPPORTED_CONTENT_TYPES'):
            return self.agent.SUPPORTED_CONTENT_TYPES
        return ["text/plain", "multipart/mixed"]
    
    async def _recovery_monitor(self):
        """Background recovery monitoring."""
        while True:
            try:
                await asyncio.sleep(self.recovery_check_interval)
                
                if self.health.state in [HandlerState.FAILED, HandlerState.CIRCUIT_OPEN]:
                    await self._attempt_recovery()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in recovery monitoring for {self._name}: {e}")
    
    async def _attempt_recovery(self):
        """Attempt to recover the agent."""
        if self._recovery_in_progress:
            return
            
        current_time = time.time()
        
        # Check circuit breaker timeout
        if (self.health.state == HandlerState.CIRCUIT_OPEN and 
            self.health.circuit_opened_at and
            (current_time - self.health.circuit_opened_at) < self.circuit_breaker_timeout):
            return
        
        # Rate limit recovery attempts
        if (self.health.last_recovery_attempt and 
            (current_time - self.health.last_recovery_attempt) < 60.0):
            return
        
        self._recovery_in_progress = True
        self.health.last_recovery_attempt = current_time
        self.health.recovery_attempts += 1
        
        logger.info(f"Attempting recovery for handler {self._name} (attempt {self.health.recovery_attempts})")
        
        try:
            self.health.state = HandlerState.RECOVERING
            
            # Try generic recovery methods
            recovery_successful = False
            
            # Method 1: Try initialize_tools (common for tool-based agents)
            if hasattr(self.agent, 'initialize_tools'):
                try:
                    await self.agent.initialize_tools()
                    recovery_successful = True
                except Exception as e:
                    logger.debug(f"initialize_tools failed: {e}")
            
            # Method 2: Try initialize (general initialization)
            if not recovery_successful and hasattr(self.agent, 'initialize'):
                try:
                    await self.agent.initialize()
                    recovery_successful = True
                except Exception as e:
                    logger.debug(f"initialize failed: {e}")
            
            # Method 3: ADK-specific recovery
            if not recovery_successful and self._is_adk_agent(self.agent):
                try:
                    # ADK agents are typically stateless, so just mark as recovered
                    recovery_successful = True
                except Exception as e:
                    logger.debug(f"ADK recovery failed: {e}")
            
            if recovery_successful:
                self.health.state = HandlerState.HEALTHY
                self.health.consecutive_failures = 0
                self.health.circuit_opened_at = None
                logger.info(f"Recovery successful for handler {self._name}")
            else:
                self.health.state = HandlerState.FAILED
                logger.warning(f"Recovery failed for handler {self._name}")
                    
        except Exception as e:
            logger.error(f"Recovery failed for handler {self._name}: {e}")
            self.health.state = HandlerState.FAILED
            self.health.last_error = str(e)
        finally:
            self._recovery_in_progress = False
    
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
        """Process task with retry logic and circuit breaker."""
        
        # Check circuit breaker
        if self.health.state == HandlerState.CIRCUIT_OPEN:
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(
                    state=TaskState.failed,
                    message=None
                ),
                final=True
            )
            return
        
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
                    logger.info(f"Retrying task {task_id} for {self._name} (attempt {attempt + 1})")
                
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
                
        else:
            raise RuntimeError(f"Agent {self._name} has unsupported interface: {self._agent_interface}")
    
    async def _adapt_complete_agent(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator:
        """Adapt an agent with complete method to the TaskHandler interface with cross-agent session support."""
        try:
            user_content = self._extract_message_content(message)
            
            # CROSS-AGENT SESSION DEBUG - FIXED VERSION
            logger.info(f"🔍 CROSS-AGENT SESSION DEBUG for {self._name}")
            logger.info(f"🔍 Session ID: {session_id}")
            logger.info(f"🔍 Handler sandbox: {self.sandbox_id}")
            logger.info(f"🔍 Session sharing: {self.session_sharing}")
            logger.info(f"🔍 Shared sandbox group: {self.shared_sandbox_group}")
            logger.info(f"🔍 User content: {user_content}")
            
            # *** FIXED: Proper session sharing detection for external CHUK storage ***
            logger.info(f"🔍 SessionAwareTaskHandler uses external CHUK storage (no _shared_sessions)")
            
            # Check session sharing configuration
            if self.session_sharing:
                target_sandbox = self.shared_sandbox_group or self.sandbox_id
                logger.info(f"🔍 Using SHARED external sessions in sandbox: {target_sandbox}")
                
                # Try to get session manager to check if session exists
                try:
                    ai_session = await self._get_ai_session_manager(session_id)
                    if ai_session:
                        logger.info(f"🔍 Successfully created AI session manager for: {session_id}")
                    else:
                        logger.warning(f"🔍 Failed to create AI session manager for: {session_id}")
                except Exception as e:
                    logger.warning(f"🔍 Error creating AI session manager: {e}")
            else:
                logger.info(f"🔍 Using ISOLATED external sessions in sandbox: {self.sandbox_id}")
            
            # Debug session statistics
            session_stats = self.get_session_stats()
            logger.info(f"🔍 Session stats: {session_stats}")
            
            # Initialize tools if available
            if hasattr(self.agent, 'initialize_tools'):
                await self.agent.initialize_tools()
            
            # **CRITICAL FIX: Get conversation context from handler's session management**
            context_messages = await self.get_conversation_context(session_id, max_messages=20)
            logger.info(f"🔍 Retrieved {len(context_messages)} context messages from external CHUK storage")
            
            # Debug context messages in detail
            if context_messages:
                logger.info(f"🔍 Context messages preview:")
                for i, ctx_msg in enumerate(context_messages[-5:]):  # Show last 5
                    role = ctx_msg.get('role', 'unknown')
                    content = ctx_msg.get('content', '')[:100]
                    logger.info(f"🔍   Context {i}: {role} - {content}...")
            else:
                logger.warning(f"🔍 No context messages found - checking why...")
                
                # Debug: Try to get full conversation history
                full_history = await self.get_conversation_history(session_id)
                logger.info(f"🔍 Full conversation history length: {len(full_history)}")
                
                if not full_history:
                    logger.warning(f"🔍 No conversation history found for session {session_id}")
                    logger.warning(f"🔍 This suggests the session either doesn't exist or hasn't been created yet")
                
                # Check if we can access the AI session manager directly
                try:
                    ai_session = await self._get_ai_session_manager(session_id)
                    if ai_session:
                        logger.info(f"🔍 AI session manager created successfully")
                        # Try to get conversation directly
                        direct_conversation = await ai_session.get_conversation()
                        logger.info(f"🔍 Direct conversation query returned {len(direct_conversation)} messages")
                    else:
                        logger.error(f"🔍 Failed to create AI session manager")
                except Exception as e:
                    logger.error(f"🔍 Error accessing AI session manager: {e}")
            
            # Check session sharing configuration one more time
            if hasattr(self, 'session_sharing') and self.session_sharing:
                shared_group = getattr(self, 'shared_sandbox_group', 'unknown')
                logger.info(f"🔍 Session sharing ENABLED - shared group: {shared_group}")
            else:
                logger.info(f"🔍 Session sharing DISABLED - isolated sandbox: {self.sandbox_id}")
            
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
            
            # **KEY FIX: Add conversation context from handler's shared sessions**
            messages.extend(context_messages)
            logger.info(f"🔍 Added {len(context_messages)} context messages to agent input")
            
            # Add current message
            messages.append({"role": "user", "content": user_content})
            
            logger.info(f"🔍 Total messages to agent: {len(messages)}")
            
            # Use complete method - agent will see full conversation history
            result = await self.agent.complete(messages, use_tools=True, session_id=session_id)
            
            # Convert result to A2A artifacts
            content = result.get("content", "No response generated")
            logger.info(f"🔍 Agent response: {content[:100]}...")
            
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
            logger.exception("Complete agent adaptation error:")
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
            
            # Use chat method
            result = await self.agent.chat(user_content, session_id=session_id)
            
            # Emit response
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=result)],
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
            
            # Use invoke method
            result = await asyncio.to_thread(self.agent.invoke, user_content, session_id=session_id)
            
            # Emit response
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=result)],
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
            
            logger.info(f"Adapting ADK agent {self._name} with content: {user_content[:100]}...")
            
            # Try different ADK interfaces in order of preference
            result = None
            
            # Method 1: Use ADK adapter if available (best integration)
            if hasattr(self.agent, 'invoke'):
                try:
                    result = await asyncio.to_thread(self.agent.invoke, user_content, session_id)
                    logger.info(f"ADK agent used invoke method")
                except Exception as e:
                    logger.debug(f"ADK invoke failed: {e}")
            
            # Method 2: Use run_async
            if result is None and hasattr(self.agent, 'run_async'):
                try:
                    # Import ADK types
                    from google.genai import types
                    
                    content_obj = types.Content(
                        role="user", 
                        parts=[types.Part.from_text(text=user_content)]
                    )
                    
                    # Run async and collect results
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
                        logger.info(f"ADK agent used run_async method")
                    
                except Exception as e:
                    logger.debug(f"ADK run_async failed: {e}")
            
            # Method 3: Use run_live
            if result is None and hasattr(self.agent, 'run_live'):
                try:
                    # Import ADK types
                    from google.genai import types
                    
                    content_obj = types.Content(
                        role="user", 
                        parts=[types.Part.from_text(text=user_content)]
                    )
                    
                    # Run live and collect results
                    events = list(self.agent.run_live(
                        user_id="a2a_user",
                        session_id=session_id or "default",
                        new_message=content_obj
                    ))
                    
                    if events and events[-1].content and events[-1].content.parts:
                        result = "".join(
                            p.text for p in events[-1].content.parts 
                            if getattr(p, "text", None)
                        )
                        logger.info(f"ADK agent used run_live method")
                    
                except Exception as e:
                    logger.debug(f"ADK run_live failed: {e}")
            
            # Fallback: Try to extract instruction and use simple generation
            if result is None:
                instruction = getattr(self.agent, 'instruction', '') or getattr(self.agent, 'global_instruction', '')
                if instruction:
                    result = f"I'm {instruction}. You asked: {user_content}\n\nI apologize, but I'm having trouble processing your request right now."
                else:
                    result = "I apologize, but I'm having trouble processing your request right now."
                logger.warning(f"ADK agent fallback used for {self._name}")
            
            logger.info(f"ADK agent response: {result[:100]}...")
            
            # Emit response
            response_artifact = Artifact(
                name="response",
                parts=[TextPart(type="text", text=result or "No response generated")],
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
            logger.error(f"Error adapting ADK agent {self._name}: {e}")
            logger.exception("ADK agent adaptation error:")
            raise
    
    def _record_task_success(self):
        """Record a successful task completion."""
        self.health.successful_tasks += 1
        self.health.last_success = time.time()
        self.health.consecutive_failures = 0
        
        if self.health.state in [HandlerState.DEGRADED, HandlerState.RECOVERING]:
            self.health.state = HandlerState.HEALTHY
            logger.info(f"Handler {self._name} recovered")
    
    def _record_task_failure(self, error: str):
        """Record a failed task and update circuit breaker."""
        self.health.last_failure = time.time()
        self.health.consecutive_failures += 1
        self.health.last_error = error
        
        # Check circuit breaker
        if self.health.consecutive_failures >= self.circuit_breaker_threshold:
            self.health.state = HandlerState.CIRCUIT_OPEN
            self.health.circuit_opened_at = time.time()
            logger.warning(f"Circuit breaker opened for handler {self._name} after {self.health.consecutive_failures} failures")
        else:
            self.health.state = HandlerState.DEGRADED
    
    async def process_task(
        self, 
        task_id: str, 
        message: Message, 
        session_id: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator:
        """Process a task with resilience and retry logic."""
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
        """Get comprehensive health status."""
        agent_health = {}
        if hasattr(self.agent, 'get_health_status'):
            try:
                agent_health = self.agent.get_health_status()
            except Exception as e:
                agent_health = {"error": str(e)}
        
        # Include session statistics
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
                "consecutive_failures": self.health.consecutive_failures,
                "success_rate": self.health.successful_tasks / max(self.health.total_tasks, 1),
                "last_success": self.health.last_success,
                "last_failure": self.health.last_failure
            },
            "recovery": {
                "attempts": self.health.recovery_attempts,
                "last_attempt": self.health.last_recovery_attempt,
                "in_progress": self._recovery_in_progress
            },
            "circuit_breaker": {
                "threshold": self.circuit_breaker_threshold,
                "timeout": self.circuit_breaker_timeout,
                "opened_at": self.health.circuit_opened_at
            },
            "session_stats": session_stats,
            "agent_health": agent_health,
            "last_error": self.health.last_error
        }
    
    async def shutdown(self):
        """Cleanup resources."""
        if self._recovery_task and not self._recovery_task.done():
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass
        
        if hasattr(self.agent, 'shutdown'):
            try:
                await self.agent.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down agent for {self._name}: {e}")


# Export the resilient handler
__all__ = ["ResilientHandler"]