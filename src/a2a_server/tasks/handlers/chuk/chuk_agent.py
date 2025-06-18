# a2a_server/tasks/handlers/chuk/chuk_agent.py
"""
Modern ChukAgent using chuk_llm and chuk_ai_session_manager.

This is the main agent class that provides unified LLM access with
built-in session management and conversation tracking.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator, Union

from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

# Modern CHUK imports - Fixed for compatibility
try:
    from chuk_llm import get_client
    # Try to import specific functions, fall back to client-based approach
    try:
        from chuk_llm import (
            ask_openai_gpt4o_mini,
            ask_anthropic_claude_sonnet4_20250514,
            ask_anthropic_sonnet,
            ask_groq_llama,
        )
        DIRECT_FUNCTIONS_AVAILABLE = True
    except ImportError:
        DIRECT_FUNCTIONS_AVAILABLE = False
        logger = logging.getLogger(__name__)
        logger.warning("Direct chuk_llm functions not available, using client-based approach")
except ImportError:
    # Fallback if chuk_llm is not available
    DIRECT_FUNCTIONS_AVAILABLE = False
    get_client = None
    logger = logging.getLogger(__name__)
    logger.error("chuk_llm not available, ChukAgent functionality will be limited")

from a2a_server.tasks.handlers.session_aware_task_handler import SessionAwareTaskHandler

logger = logging.getLogger(__name__)


class ChukAgent(SessionAwareTaskHandler):
    """
    Modern CHUK Agent with unified LLM interface and session management.
    
    Features:
    - Multiple LLM providers via chuk_llm
    - Automatic conversation tracking via SessionAwareTaskHandler
    - Infinite context with segmentation
    - Token usage monitoring
    - Tool integration support (future)
    """
    
    # Mark as abstract to exclude from automatic discovery
    abstract = True
    
    def __init__(
        self,
        name: str,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        instruction: str = "",
        description: str = "",
        streaming: bool = True,
        enable_tools: bool = False,
        tools: Optional[List[Dict]] = None,
        **session_kwargs
    ):
        """
        Initialize a ChukAgent.
        
        Args:
            name: Agent name
            provider: LLM provider (openai, anthropic, groq)
            model: Model name (gpt-4o-mini, claude-sonnet-4, etc.)
            instruction: System prompt/instructions
            description: Agent description
            streaming: Whether to use streaming responses
            enable_tools: Whether to enable tool calling
            tools: List of tool definitions
            **session_kwargs: Additional session management arguments
        """
        # Initialize session management
        super().__init__(name, **session_kwargs)
        
        self.provider = provider
        self.model = model
        self.instruction = instruction or f"You are {name}, a helpful AI assistant."
        self.description = description
        self.streaming = streaming
        self.enable_tools = enable_tools
        self.tools = tools or []
        
        # Initialize LLM client lazily
        self._client = None
        
        # Check if chuk_llm is available
        if get_client is None:
            logger.warning(f"ChukAgent '{name}' initialized without chuk_llm support")
        
        logger.info(
            "Initialized ChukAgent '%s' (%s/%s, streaming=%s, tools=%s)",
            name, provider, model, streaming, enable_tools
        )
    
    @property
    def client(self):
        """Lazy-initialize LLM client."""
        if self._client is None and get_client is not None:
            try:
                self._client = get_client(provider=self.provider, model=self.model)
            except Exception as e:
                logger.error(f"Failed to initialize LLM client: {e}")
                self._client = None
        return self._client
    
    def _extract_message_content(self, message: Message) -> str:
        """Extract text content from A2A message."""
        if not message.parts:
            return str(message) if message else ""
        
        text_parts = []
        for part in message.parts:
            try:
                part_data = part.model_dump(exclude_none=True) if hasattr(part, "model_dump") else {}
                if part_data.get("type") == "text" and "text" in part_data:
                    text_parts.append(part_data["text"])
                elif hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
            except Exception:
                pass
        
        return " ".join(text_parts) if text_parts else str(message)
    
    async def _call_llm_direct(self, user_message: str) -> str:
        """Call LLM using direct functions if available."""
        if not DIRECT_FUNCTIONS_AVAILABLE:
            raise NotImplementedError("Direct LLM functions not available")
        
        try:
            if self.provider == "openai" and self.model == "gpt-4o-mini":
                return await ask_openai_gpt4o_mini(user_message)
            elif self.provider == "anthropic":
                if "sonnet" in self.model.lower():
                    return await ask_anthropic_sonnet(user_message)
                elif "claude-sonnet-4" in self.model:
                    return await ask_anthropic_claude_sonnet4_20250514(user_message)
            elif self.provider == "groq":
                return await ask_groq_llama(user_message)
            else:
                raise NotImplementedError(f"No direct function for {self.provider}/{self.model}")
        except Exception as e:
            logger.error(f"Direct LLM call failed: {e}")
            raise
    
    async def _call_llm_client(
        self, 
        user_message: str, 
        conversation_context: List[Dict[str, str]] = None
    ) -> str:
        """Call LLM using client-based approach."""
        if self.client is None:
            raise RuntimeError("LLM client not available")
        
        # Build messages for LLM
        messages = [{"role": "system", "content": self.instruction}]
        
        # Add conversation context
        if conversation_context:
            messages.extend(conversation_context[-10:])  # Last 10 messages
        
        # Add current message if not already included
        if not conversation_context or conversation_context[-1]["content"] != user_message:
            messages.append({"role": "user", "content": user_message})
        
        try:
            completion = await self.client.create_completion(messages=messages)
            return self._extract_completion_response(completion)
        except Exception as e:
            logger.error(f"Client LLM call failed: {e}")
            raise
    
    async def _call_llm(
        self, 
        user_message: str, 
        conversation_context: List[Dict[str, str]] = None
    ) -> str:
        """Call LLM with fallback approach."""
        # Try direct functions first (simpler, faster)
        if DIRECT_FUNCTIONS_AVAILABLE and not conversation_context:
            try:
                return await self._call_llm_direct(user_message)
            except (NotImplementedError, Exception) as e:
                logger.debug(f"Direct LLM call failed, trying client: {e}")
        
        # Fall back to client-based approach
        return await self._call_llm_client(user_message, conversation_context)
    
    def _extract_completion_response(self, completion) -> str:
        """Extract response text from completion object."""
        if isinstance(completion, dict):
            return completion.get("response", completion.get("content", str(completion)))
        elif hasattr(completion, 'choices') and completion.choices:
            return completion.choices[0].message.content or ""
        else:
            return str(completion) if completion is not None else ""
    
    async def _call_llm_with_tools(
        self,
        user_message: str,
        conversation_context: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Call LLM with tool support (placeholder for future implementation)."""
        # For now, just call regular LLM
        response = await self._call_llm(user_message, conversation_context)
        return {
            "response": response,
            "tool_calls": [],
            "tool_results": []
        }
    
    async def process_task(
        self,
        task_id: str,
        message: Message,
        session_id: Optional[str] = None
    ) -> AsyncGenerator[TaskStatusUpdateEvent | TaskArtifactUpdateEvent, None]:
        """Process a task with modern CHUK integration."""
        # Check if LLM is available
        if get_client is None and not DIRECT_FUNCTIONS_AVAILABLE:
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
            error_artifact = Artifact(
                name="error",
                parts=[TextPart(type="text", text="LLM client not available - chuk_llm not properly installed")],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=error_artifact)
            return
        
        # Extract user message
        user_message = self._extract_message_content(message)
        
        # Yield working status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        try:
            # Add user message to conversation
            await self.add_user_message(session_id, user_message)
            
            # Get conversation context
            context = await self.get_conversation_context(session_id)
            
            # Call LLM
            if self.enable_tools and self.tools:
                result = await self._call_llm_with_tools(user_message, context)
                response = result["response"]
                tool_calls = result.get("tool_calls", [])
                
                # Handle tool calls if present (future implementation)
                if tool_calls:
                    for i, tool_call in enumerate(tool_calls):
                        tool_artifact = Artifact(
                            name=f"tool_call_{i}",
                            parts=[TextPart(
                                type="text", 
                                text=f"Tool: {tool_call.get('name', 'unknown')}"
                            )],
                            index=i + 1
                        )
                        yield TaskArtifactUpdateEvent(id=task_id, artifact=tool_artifact)
            else:
                response = await self._call_llm(user_message, context)
            
            # Add AI response to conversation
            await self.add_ai_response(session_id, response, self.model, self.provider)
            
            # Emit response artifact
            response_artifact = Artifact(
                name=f"{self.name}_response",
                parts=[TextPart(type="text", text=response)],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=response_artifact)
            
            # Yield completion
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error("Error processing task %s: %s", task_id, e)
            
            # Emit error artifact
            error_artifact = Artifact(
                name="error",
                parts=[TextPart(type="text", text=f"Error: {str(e)}")],
                index=0
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=error_artifact)
            
            # Yield failed status
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )


# Factory functions for common agent configurations
def create_openai_agent(
    name: str,
    model: str = "gpt-4o-mini",
    instruction: str = "",
    **kwargs
) -> ChukAgent:
    """Create OpenAI-powered agent."""
    return ChukAgent(
        name=name,
        provider="openai",
        model=model,
        instruction=instruction,
        **kwargs
    )

def create_anthropic_agent(
    name: str,
    model: str = "claude-sonnet-4",
    instruction: str = "",
    **kwargs
) -> ChukAgent:
    """Create Anthropic-powered agent."""
    return ChukAgent(
        name=name,
        provider="anthropic", 
        model=model,
        instruction=instruction,
        **kwargs
    )

def create_groq_agent(
    name: str,
    model: str = "llama-3",
    instruction: str = "",
    **kwargs
) -> ChukAgent:
    """Create Groq-powered agent."""
    return ChukAgent(
        name=name,
        provider="groq",
        model=model,
        instruction=instruction,
        **kwargs
    )

# Enhanced create_agent_with_mcp function
# Add this to replace the placeholder at the bottom of chuk_agent.py

def create_agent_with_mcp(
    name: str,
    description: str = "",
    instruction: str = "",
    mcp_servers: list = None,
    mcp_config_file: str = None,
    tool_namespace: str = "",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    streaming: bool = True,
    **kwargs
) -> ChukAgent:
    """
    Create a ChukAgent with MCP (Model Context Protocol) tool support.
    
    Args:
        name: Agent name
        description: Agent description
        instruction: System prompt/instructions
        mcp_servers: List of MCP server names to connect to
        mcp_config_file: Path to MCP configuration file
        tool_namespace: Namespace for MCP tools
        provider: LLM provider
        model: LLM model
        streaming: Enable streaming responses
        **kwargs: Additional arguments
        
    Returns:
        ChukAgent instance with MCP tool support
    """
    
    # Try to set up MCP integration
    mcp_tools = []
    mcp_initialized = False
    
    if mcp_servers and mcp_config_file:
        try:
            # Try to import MCP setup functionality
            from chuk_tool_processor.mcp.setup_mcp_sse import setup_mcp_sse
            import json
            from pathlib import Path
            
            # Load MCP configuration
            config_path = Path(mcp_config_file)
            if config_path.exists():
                with open(config_path) as f:
                    mcp_config = json.load(f)
                
                # Extract server configurations
                servers = []
                server_names = {}
                
                for i, server_name in enumerate(mcp_servers):
                    if server_name in mcp_config.get("mcpServers", {}):
                        server_config = mcp_config["mcpServers"][server_name]
                        servers.append({
                            "name": server_name,
                            "url": f"stdio://{server_config['command']}",  # Convert to URL format
                            "transport": "stdio",
                            "command": server_config["command"],
                            "args": server_config.get("args", [])
                        })
                        server_names[i] = server_name
                
                if servers:
                    logger.info(f"Setting up MCP integration for {name} with servers: {mcp_servers}")
                    
                    # Initialize MCP connection
                    # Note: This is a simplified example - actual implementation would need
                    # proper async initialization and error handling
                    
                    # For now, create tool definitions based on known MCP server capabilities
                    if "time" in mcp_servers:
                        mcp_tools.extend([
                            {
                                "type": "function",
                                "function": {
                                    "name": "get_current_time",
                                    "description": "Get current time in specified timezone",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "timezone": {
                                                "type": "string",
                                                "description": "IANA timezone name (e.g., America/New_York)"
                                            }
                                        },
                                        "required": ["timezone"]
                                    }
                                }
                            },
                            {
                                "type": "function", 
                                "function": {
                                    "name": "convert_time",
                                    "description": "Convert time between timezones",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "time": {"type": "string", "description": "Time to convert"},
                                            "from_tz": {"type": "string", "description": "Source timezone"},
                                            "to_tz": {"type": "string", "description": "Target timezone"}
                                        },
                                        "required": ["time", "from_tz", "to_tz"]
                                    }
                                }
                            }
                        ])
                    
                    if "weather" in mcp_servers:
                        mcp_tools.extend([
                            {
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "description": "Get current weather for a location",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "location": {
                                                "type": "string",
                                                "description": "City name or location"
                                            }
                                        },
                                        "required": ["location"]
                                    }
                                }
                            },
                            {
                                "type": "function",
                                "function": {
                                    "name": "get_forecast",
                                    "description": "Get weather forecast for a location",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "location": {"type": "string", "description": "City name"},
                                            "days": {"type": "integer", "description": "Number of days", "default": 5}
                                        },
                                        "required": ["location"]
                                    }
                                }
                            }
                        ])
                    
                    mcp_initialized = True
                    logger.info(f"MCP integration initialized for {name} with {len(mcp_tools)} tools")
                    
        except ImportError as e:
            logger.warning(f"MCP dependencies not available for {name}: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize MCP for {name}: {e}")
    
    # Create agent with or without MCP tools
    if mcp_initialized and mcp_tools:
        # Enhanced instruction with tool awareness
        enhanced_instruction = instruction or f"""
You are {name}, a helpful AI assistant with access to specialized tools.

{description}

You have access to the following tools:
{', '.join([tool['function']['name'] for tool in mcp_tools])}

When users ask questions that can be answered with your tools, always use them to provide accurate, real-time information.
"""
        
        agent = ChukAgent(
            name=name,
            provider=provider,
            model=model,
            instruction=enhanced_instruction,
            description=description,
            streaming=streaming,
            enable_tools=True,
            tools=mcp_tools,
            **kwargs
        )
        
        logger.info(f"Created MCP-enabled agent '{name}' with {len(mcp_tools)} tools")
        return agent
    
    else:
        # Fallback to basic agent with helpful instruction about missing tools
        fallback_instruction = instruction or f"""
You are {name}, a helpful AI assistant. {description}

Note: Advanced tool capabilities are currently unavailable, but you can still provide helpful information and guidance on {', '.join(mcp_servers or ['general topics'])}.
"""
        
        agent = ChukAgent(
            name=name,
            provider=provider,
            model=model,
            instruction=fallback_instruction,
            description=description,
            streaming=streaming,
            enable_tools=False,
            **kwargs
        )
        
        logger.warning(f"Created basic agent '{name}' - MCP tools not available")
        return agent
    
# Export main class and factory functions
__all__ = [
    "ChukAgent",
    "create_openai_agent",
    "create_anthropic_agent", 
    "create_groq_agent",
    "create_agent_with_mcp"
]