# a2a_server/tasks/handlers/chuk/chuk_agent.py (CORRECTED - Pure Agent)
"""
Pure ChukAgent class - framework agnostic, no A2A dependencies.
"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, Union
from pathlib import Path

# chuk-llm imports
from chuk_llm.llm.client import get_client
from chuk_llm.llm.system_prompt_generator import SystemPromptGenerator

# chuk-tool-processor imports
from chuk_tool_processor.registry.provider import ToolRegistryProvider
from chuk_tool_processor.mcp.setup_mcp_stdio import setup_mcp_stdio
from chuk_tool_processor.mcp.setup_mcp_sse import setup_mcp_sse
from chuk_tool_processor.execution.tool_executor import ToolExecutor
from chuk_tool_processor.execution.strategies.inprocess_strategy import InProcessStrategy
from chuk_tool_processor.models.tool_call import ToolCall

# Internal session management (optional - agent can manage its own sessions)
try:
    from chuk_ai_session_manager import SessionManager as AISessionManager
    from chuk_ai_session_manager.session_storage import setup_chuk_sessions_storage
    HAS_SESSION_SUPPORT = True
except ImportError:
    HAS_SESSION_SUPPORT = False

logger = logging.getLogger(__name__)


class ChukAgent:
    """
    Pure ChukAgent - framework agnostic with MCP tool support and optional session management.
    
    This is a pure agent class that can be used in any framework, not just A2A.
    It handles its own sessions internally and provides simple chat/complete interfaces.
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        instruction: str = "",
        provider: str = "openai",
        model: Optional[str] = None,
        use_system_prompt_generator: bool = False,
        
        # MCP Configuration
        mcp_config_file: Optional[str] = None,
        mcp_servers: Optional[List[str]] = None,
        mcp_transport: str = "stdio",
        mcp_sse_servers: Optional[List[Dict[str, str]]] = None,
        namespace: str = "tools",
        max_concurrency: int = 4,
        tool_timeout: float = 30.0,
        
        # Agent-internal session management (optional)
        enable_sessions: bool = True,
        infinite_context: bool = True,
        token_threshold: int = 4000,
        max_turns_per_segment: int = 50,
        session_ttl_hours: int = 24,
        
        # Other options
        streaming: bool = False,
        **kwargs
    ):
        """Initialize ChukAgent with optional internal session management."""
        
        # Core agent configuration
        self.name = name
        self.description = description
        self.instruction = instruction or f"You are {name}, a helpful AI assistant."
        self.provider = provider
        self.model = model
        self.use_system_prompt_generator = use_system_prompt_generator
        self.streaming = streaming
        
        # MCP configuration
        self.mcp_config_file = mcp_config_file
        self.mcp_servers = mcp_servers or []
        self.mcp_transport = mcp_transport
        self.mcp_sse_servers = mcp_sse_servers or []
        self.namespace = namespace
        self.max_concurrency = max_concurrency
        self.tool_timeout = tool_timeout
        
        # Tool components (lazy initialization)
        self.registry = None
        self.executor = None
        self.stream_manager = None
        self._tools_initialized = False
        
        # Internal session management (agent's own sessions, not A2A's)
        self.enable_sessions = enable_sessions and HAS_SESSION_SUPPORT
        if self.enable_sessions:
            self._setup_internal_sessions(
                infinite_context=infinite_context,
                token_threshold=token_threshold,
                max_turns_per_segment=max_turns_per_segment,
                session_ttl_hours=session_ttl_hours
            )
        else:
            self._ai_sessions = {}
        
        logger.info(f"Initialized ChukAgent '{name}' with {mcp_transport} MCP transport")

    def _setup_internal_sessions(
        self, 
        infinite_context: bool,
        token_threshold: int, 
        max_turns_per_segment: int,
        session_ttl_hours: int
    ):
        """Setup agent's internal session management."""
        try:
            # Setup storage for this agent's sessions
            sandbox_id = f"chuk-agent-{self.name.lower().replace('_', '-')}"
            setup_chuk_sessions_storage(
                sandbox_id=sandbox_id,
                default_ttl_hours=session_ttl_hours
            )
            
            self.session_config = {
                "infinite_context": infinite_context,
                "token_threshold": token_threshold, 
                "max_turns_per_segment": max_turns_per_segment
            }
            
            # Track agent's own AI session managers
            self._ai_sessions: Dict[str, AISessionManager] = {}
            
            logger.debug(f"Agent {self.name} session management enabled (sandbox: {sandbox_id})")
            
        except Exception as e:
            logger.warning(f"Failed to setup sessions for agent {self.name}: {e}")
            self.enable_sessions = False
            self._ai_sessions = {}

    def _get_ai_session(self, session_id: Optional[str]) -> Optional[AISessionManager]:
        """Get or create AI session manager for internal session tracking."""
        if not self.enable_sessions or not session_id:
            return None
            
        if session_id not in self._ai_sessions:
            try:
                self._ai_sessions[session_id] = AISessionManager(**self.session_config)
            except Exception as e:
                logger.error(f"Failed to create AI session {session_id}: {e}")
                return None
                
        return self._ai_sessions[session_id]

    def get_system_prompt(self) -> str:
        """Get system prompt, optionally using chuk_llm's generator."""
        if self.use_system_prompt_generator:
            generator = SystemPromptGenerator()
            base_prompt = generator.generate_prompt({})
            return f"{base_prompt}\n\n{self.instruction}"
        else:
            return self.instruction

    async def get_llm_client(self):
        """Get LLM client for this agent."""
        return get_client(provider=self.provider, model=self.model)

    def _extract_response_content(self, response) -> str:
        """Extract content from chuk_llm response."""
        if isinstance(response, dict):
            return response.get("response", response.get("content", str(response)))
        elif hasattr(response, 'content'):
            return response.content or ""
        elif hasattr(response, 'response'):
            return response.response or ""
        else:
            return str(response) if response is not None else ""

    async def initialize_tools(self):
        """Initialize MCP connection and tools."""
        if self._tools_initialized:
            return
            
        try:
            if self.mcp_transport == "stdio" and self.mcp_servers and self.mcp_config_file:
                server_names = {i: name for i, name in enumerate(self.mcp_servers)}
                
                logger.info(f"Setting up stdio MCP with servers: {self.mcp_servers}")
                _, self.stream_manager = await setup_mcp_stdio(
                    config_file=self.mcp_config_file,
                    servers=self.mcp_servers,
                    server_names=server_names,
                    namespace=self.namespace,
                )
                
            elif self.mcp_transport == "sse" and self.mcp_sse_servers:
                server_names = {i: server["name"] for i, server in enumerate(self.mcp_sse_servers)}
                
                logger.info(f"Setting up SSE MCP with servers: {[s['name'] for s in self.mcp_sse_servers]}")
                _, self.stream_manager = await setup_mcp_sse(
                    servers=self.mcp_sse_servers,
                    server_names=server_names,
                    namespace=self.namespace,
                )
            
            if self.stream_manager:
                self.registry = await ToolRegistryProvider.get_registry()
                
                strategy = InProcessStrategy(
                    self.registry,
                    default_timeout=self.tool_timeout,
                    max_concurrency=self.max_concurrency,
                )
                self.executor = ToolExecutor(self.registry, strategy=strategy)
                
                self._tools_initialized = True
                logger.info(f"MCP initialized successfully with namespace '{self.namespace}'")
            
        except Exception as e:
            logger.error(f"Failed to initialize MCP: {e}")
            self._tools_initialized = False

    async def get_available_tools(self) -> List[str]:
        """Get list of available tools."""
        if not self.registry:
            return []
            
        try:
            tools = await self.registry.list_tools()
            return [name for ns, name in tools if ns == self.namespace]
        except Exception as e:
            logger.error(f"Error getting tools: {e}")
            return []

    async def execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute tool calls using actual MCP parameters (FIXED)."""
        if not self.executor:
            return [{"error": "Tool executor not initialized"} for _ in tool_calls]
        
        # Convert to ToolCall objects with proper argument handling
        calls = []
        for tc in tool_calls:
            # Handle both dict and object formats
            if isinstance(tc, dict):
                func = tc.get("function", {})
                tool_call_id = tc.get("id", "unknown")
            else:
                func = getattr(tc, 'function', {})
                tool_call_id = getattr(tc, 'id', 'unknown')
            
            tool_name = func.get("name", "") if isinstance(func, dict) else getattr(func, 'name', '')
            
            # Remove namespace prefix if present
            if tool_name.startswith(f"{self.namespace}."):
                tool_name = tool_name[len(f"{self.namespace}."):]
            
            # Parse arguments - NO MORE GENERIC WRAPPER
            args = func.get("arguments", {}) if isinstance(func, dict) else getattr(func, 'arguments', {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse tool arguments: {args}, error: {e}")
                    args = {}
            
            # Create ToolCall with actual arguments (not wrapped)
            calls.append(ToolCall(
                tool=f"{self.namespace}.{tool_name}",
                arguments=args  # Use actual arguments, not {"query": args}
            ))
            
            logger.debug(f"Executing tool {tool_name} with args: {args}")
        
        try:
            results = await self.executor.execute(calls)
            
            # Format results
            formatted_results = []
            for tc, result in zip(tool_calls, results):
                # Handle both dict and object formats for tool_call_id
                if isinstance(tc, dict):
                    tool_call_id = tc.get("id", "unknown")
                else:
                    tool_call_id = getattr(tc, 'id', 'unknown')
                
                if result.error:
                    formatted_results.append({
                        "tool_call_id": tool_call_id,
                        "content": f"Error: {result.error}"
                    })
                else:
                    content = result.result
                    if isinstance(content, (dict, list)):
                        content = json.dumps(content, indent=2)
                    elif content is None:
                        content = "No result"
                    
                    formatted_results.append({
                        "tool_call_id": tool_call_id, 
                        "content": str(content)
                    })
            
            logger.info(f"Tool execution completed: {len(formatted_results)} results")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return [{"error": str(e)} for _ in tool_calls]

    async def generate_tools_schema(self) -> List[Dict[str, Any]]:
        """Generate OpenAI-style tool schema using actual MCP tool definitions."""
        if not self.registry:
            return []
        
        tools = []
        try:
            # Get all tools with their actual schemas
            tool_list = await self.registry.list_tools()
            
            for namespace, tool_name in tool_list:
                if namespace != self.namespace:
                    continue
                    
                try:
                    # Get the actual tool definition from registry
                    tool_def = await self.registry.get_tool(namespace, tool_name)
                    
                    if tool_def and hasattr(tool_def, 'input_schema'):
                        # Use the actual MCP schema
                        schema = tool_def.input_schema
                        
                        # Convert MCP schema to OpenAI format
                        openai_tool = {
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "description": getattr(tool_def, 'description', f"Execute {tool_name} tool"),
                                "parameters": schema if isinstance(schema, dict) else schema.model_dump() if hasattr(schema, 'model_dump') else {
                                    "type": "object",
                                    "properties": {},
                                    "required": []
                                }
                            }
                        }
                        
                        tools.append(openai_tool)
                        logger.debug(f"Added tool schema for {tool_name}: {openai_tool}")
                        
                    else:
                        logger.warning(f"No schema found for tool {namespace}.{tool_name}")
                        
                except Exception as e:
                    logger.error(f"Error getting schema for tool {namespace}.{tool_name}: {e}")
                    
            logger.info(f"Generated {len(tools)} tool schemas")
            return tools
            
        except Exception as e:
            logger.error(f"Error generating tool schemas: {e}")
            return []

    async def debug_tools(self) -> Dict[str, Any]:
        """Debug method to inspect tool configuration."""
        debug_info = {
            "registry_available": self.registry is not None,
            "executor_available": self.executor is not None,
            "tools_initialized": self._tools_initialized,
            "namespace": self.namespace,
            "available_tools": [],
            "tool_schemas": []
        }
        
        if self.registry:
            try:
                tool_list = await self.registry.list_tools()
                debug_info["available_tools"] = [(ns, name) for ns, name in tool_list if ns == self.namespace]
                
                # Get schemas for debugging
                for namespace, tool_name in tool_list:
                    if namespace == self.namespace:
                        try:
                            tool_def = await self.registry.get_tool(namespace, tool_name)
                            if tool_def:
                                schema_info = {
                                    "name": tool_name,
                                    "description": getattr(tool_def, 'description', 'No description'),
                                    "input_schema": getattr(tool_def, 'input_schema', 'No schema')
                                }
                                debug_info["tool_schemas"].append(schema_info)
                        except Exception as e:
                            debug_info["tool_schemas"].append({
                                "name": tool_name,
                                "error": str(e)
                            })
            except Exception as e:
                debug_info["registry_error"] = str(e)
        
        return debug_info

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        use_tools: bool = True,
        session_id: Optional[str] = None,
        **llm_kwargs
    ) -> Dict[str, Any]:
        """Complete a conversation with optional tool usage and session tracking."""
        await self.initialize_tools()
        
        # Add session context if available and enabled
        ai_session = self._get_ai_session(session_id) if session_id else None
        if ai_session:
            try:
                # Get recent conversation context
                context = await ai_session.get_conversation()
                if context:
                    # Insert context before the current user message
                    system_msg = messages[0] if messages and messages[0]["role"] == "system" else None
                    user_messages = messages[1:] if system_msg else messages
                    
                    enhanced_messages = []
                    if system_msg:
                        enhanced_messages.append(system_msg)
                    
                    # Add recent context (last 5 exchanges)
                    enhanced_messages.extend(context[-5:])
                    enhanced_messages.extend(user_messages)
                    messages = enhanced_messages
            except Exception as e:
                logger.warning(f"Failed to get session context: {e}")
        
        llm_client = await self.get_llm_client()
        
        # Get tools if requested and available
        tools = None
        if use_tools:
            tools = await self.generate_tools_schema()
            if not tools:
                use_tools = False
        
        # Track user message in session
        if ai_session:
            try:
                user_message = None
                for msg in reversed(messages):
                    if msg["role"] == "user":
                        user_message = msg["content"]
                        break
                if user_message:
                    await ai_session.user_says(user_message)
            except Exception as e:
                logger.warning(f"Failed to track user message: {e}")
        
        # Call LLM
        try:
            if use_tools and tools:
                response = await llm_client.create_completion(
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    **llm_kwargs
                )
                
                # Handle both dict and object responses
                tool_calls = None
                content = None
                
                if isinstance(response, dict):
                    tool_calls = response.get('tool_calls', [])
                    content = response.get('response') or response.get('content')
                else:
                    tool_calls = getattr(response, 'tool_calls', [])
                    content = getattr(response, 'content', None)
                
                # Check for tool calls
                if tool_calls:
                    logger.info(f"Processing {len(tool_calls)} tool calls")
                    
                    # Execute tools
                    tool_results = await self.execute_tools(tool_calls)
                    
                    # Add tool results to conversation and get final response
                    enhanced_messages = messages + [
                        {
                            "role": "assistant",
                            "content": content or "I'll use my tools to help you.",
                            "tool_calls": tool_calls
                        }
                    ]
                    
                    for result in tool_results:
                        enhanced_messages.append({
                            "role": "tool",
                            "tool_call_id": result.get("tool_call_id", "unknown"),
                            "content": result.get("content", "No result")
                        })
                    
                    # Get final response
                    final_response = await llm_client.create_completion(messages=enhanced_messages, **llm_kwargs)
                    final_content = self._extract_response_content(final_response)
                    
                    # Track AI response in session
                    if ai_session and final_content:
                        try:
                            await ai_session.ai_responds(final_content, model=self.model, provider=self.provider)
                        except Exception as e:
                            logger.warning(f"Failed to track AI response: {e}")
                    
                    return {
                        "content": final_content,
                        "tool_calls": tool_calls,
                        "tool_results": tool_results,
                        "usage": getattr(final_response, 'usage', None) if hasattr(final_response, 'usage') else response.get('usage')
                    }
                else:
                    # No tool calls
                    final_content = content or self._extract_response_content(response)
                    
                    # Track AI response in session
                    if ai_session and final_content:
                        try:
                            await ai_session.ai_responds(final_content, model=self.model, provider=self.provider)
                        except Exception as e:
                            logger.warning(f"Failed to track AI response: {e}")
                    
                    return {
                        "content": final_content,
                        "tool_calls": [],
                        "tool_results": [],
                        "usage": getattr(response, 'usage', None) if hasattr(response, 'usage') else response.get('usage')
                    }
            else:
                # No tools, simple completion
                response = await llm_client.create_completion(messages=messages, **llm_kwargs)
                final_content = self._extract_response_content(response)
                
                # Track AI response in session
                if ai_session and final_content:
                    try:
                        await ai_session.ai_responds(final_content, model=self.model, provider=self.provider)
                    except Exception as e:
                        logger.warning(f"Failed to track AI response: {e}")
                
                return {
                    "content": final_content,
                    "tool_calls": [],
                    "tool_results": [],
                    "usage": getattr(response, 'usage', None) if hasattr(response, 'usage') else response.get('usage')
                }
        except Exception as e:
            logger.error(f"Error in LLM completion: {e}")
            raise

    async def chat(self, user_message: str, session_id: Optional[str] = None, **kwargs) -> str:
        """Simple chat interface with session support."""
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "user", "content": user_message}
        ]
        
        result = await self.complete(messages, session_id=session_id, **kwargs)
        return result["content"] or "No response generated"

    async def get_conversation_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Get conversation history for a session."""
        ai_session = self._get_ai_session(session_id) if session_id else None
        if not ai_session:
            return []
            
        try:
            return await ai_session.get_conversation()
        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}")
            return []

    async def get_session_stats(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get session statistics."""
        ai_session = self._get_ai_session(session_id) if session_id else None
        if not ai_session:
            return {"total_tokens": 0, "estimated_cost": 0}
            
        try:
            return ai_session.get_stats()
        except Exception as e:
            logger.error(f"Failed to get session stats: {e}")
            return {"total_tokens": 0, "estimated_cost": 0}

    async def shutdown(self):
        """Cleanup MCP connections."""
        if self.stream_manager:
            try:
                await self.stream_manager.close()
                logger.info(f"Closed MCP stream manager for {self.name}")
            except Exception as e:
                logger.warning(f"Error closing stream manager: {e}")


# Export the main class
__all__ = ["ChukAgent"]