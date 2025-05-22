"""
ChukAgent: A pure agent abstraction with chuk-tool-processor as the native tool calling engine
"""
import asyncio
import json
import logging
import re
from typing import Dict, List, Any, Optional, Union, AsyncGenerator
from pathlib import Path

# chuk-llm imports
from chuk_llm.llm.llm_client import get_llm_client
from chuk_llm.llm.provider_config import ProviderConfig

# chuk-tool-processor imports (native tool calling engine)
from chuk_tool_processor.registry.provider import ToolRegistryProvider
from chuk_tool_processor.mcp.setup_mcp_stdio import setup_mcp_stdio
from chuk_tool_processor.execution.tool_executor import ToolExecutor
from chuk_tool_processor.execution.strategies.inprocess_strategy import InProcessStrategy
from chuk_tool_processor.models.tool_call import ToolCall

logger = logging.getLogger(__name__)

class ChukAgent:
    """
    A pure agent abstraction with chuk-tool-processor as the native tool calling engine.
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
        mcp_config_file: Optional[str] = None,
        mcp_servers: Optional[List[str]] = None,
        tool_namespace: str = "tools",
        max_concurrency: int = 4,
        tool_timeout: float = 30.0,
        enable_tools: bool = True
    ):
        """
        Initialize a new agent with chuk-tool-processor as the native tool engine.
        
        Args:
            name: Unique identifier for this agent
            description: Brief description of the agent's purpose
            instruction: System prompt defining the agent's personality and constraints
            provider: LLM provider to use (openai, anthropic, gemini, etc.)
            model: Specific model to use (if None, uses provider default)
            streaming: Whether to stream responses or return complete responses
            config: Optional provider configuration
            mcp_config_file: Path to MCP server configuration file
            mcp_servers: List of MCP server names to initialize
            tool_namespace: Namespace for tools in the registry
            max_concurrency: Maximum concurrent tool executions
            tool_timeout: Timeout for tool execution in seconds
            enable_tools: Whether to enable tool calling functionality
        """
        self.name = name
        self.description = description
        
        # Define a default instruction if none is provided
        default_instruction = f"""
You are a helpful assistant named {name}.

{description}
"""
        
        self.instruction = instruction or default_instruction
        self.provider = provider
        self.model = model
        self.streaming = streaming
        self.config = config or ProviderConfig()
        
        # Tool processor configuration
        self.enable_tools = enable_tools
        self.mcp_config_file = mcp_config_file
        self.mcp_servers = mcp_servers or []
        self.tool_namespace = tool_namespace
        self.max_concurrency = max_concurrency
        self.tool_timeout = tool_timeout
        
        # Tool processor components (native tool engine)
        self.registry = None
        self.executor = None
        self.stream_manager = None
        self.tools = []  # OpenAI-compatible tool schemas
        
        # Map: safe_name -> real dotted name
        self._name_map: dict[str, str] = {}
        
        self._tools_initialized = False
        
        logger.info(f"Initialized ChukAgent '{name}' using {provider}/{model or 'default'}")
        if self.enable_tools:
            logger.info(f"Tool calling enabled with {len(self.mcp_servers)} MCP servers")
    
    async def _initialize_tools(self) -> None:
        """Initialize the native chuk-tool-processor engine."""
        if self._tools_initialized or not self.enable_tools:
            return

        try:
            if self.mcp_servers and self.mcp_config_file:
                logger.info(f"Raw self.mcp_servers: {self.mcp_servers}")

                if not isinstance(self.mcp_servers, list):
                    raise ValueError("Expected self.mcp_servers to be a list")

                # ✅ Correct dict format
                server_names = {i: name for i, name in enumerate(self.mcp_servers)}
                logger.info(f"Constructed server_names: {server_names}")
                assert isinstance(server_names, dict), "server_names must be a dict[int, str]"

                # ✅ THIS LINE IS CRITICAL - Ensure namespace is never None
                namespace = self.tool_namespace if self.tool_namespace else "default"
                _, self.stream_manager = await setup_mcp_stdio(
                    config_file=self.mcp_config_file,
                    servers=self.mcp_servers,
                    server_names=server_names,  # ← not self.mcp_servers!
                    namespace=namespace
                )

                logger.info(f"Initialized {len(self.mcp_servers)} MCP servers")

            self.registry = await ToolRegistryProvider.get_registry()

            strategy = InProcessStrategy(
                self.registry,
                default_timeout=self.tool_timeout,
                max_concurrency=self.max_concurrency
            )
            self.executor = ToolExecutor(self.registry, strategy=strategy)

            await self._generate_tool_schemas()

            self._tools_initialized = True
            logger.info(f"Native tool engine initialized with {len(self.tools)} tools")

        except Exception as e:
            logger.error(f"Failed to initialize native tool engine: {e}")
            self.enable_tools = False

    async def _generate_tool_schemas(self) -> None:
        """
        Walk the registry, flatten namespaces, build one OpenAI-style schema
        *per tool* while creating a safe alias for every dotted name.
        """
        if not self.registry:
            return

        raw = await self.registry.list_tools()
        logger.info(f"Raw tools from registry: {raw}")

        # -------- helper to flatten nested dict / list output ---------------
        def walk(node, prefix=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    full = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
                    # nested namespace?
                    if getattr(v, "is_namespace", False) or isinstance(v, dict):
                        yield from walk(v, full + ".")
                    else:
                        yield full, v
            elif isinstance(node, (list, tuple)):
                # Handle tuple format like (namespace, tool_name) or list of such tuples
                for item in node:
                    if isinstance(item, tuple) and len(item) == 2:
                        namespace, tool_name = item
                        # Create full name: namespace.tool_name or just tool_name if namespace is None
                        if namespace and namespace != "None":
                            full_name = f"{namespace}.{tool_name}"
                        else:
                            full_name = tool_name
                        # Only yield the tool if it's in the primary namespace ('tools')
                        # This avoids duplicate registration
                        if namespace == "tools" or namespace is None:
                            yield full_name, tool_name  # yield (full_name, tool_info)
                    else:
                        # Fallback for other formats
                        yield prefix + item.name if prefix else item.name, item

        # --------------------------------------------------------------------
        self.tools = []
        self._name_map = {}
        seen_tools = set()  # Track seen tools to avoid duplicates

        for real_name, tool_name in walk(raw):
            # Skip duplicates
            if real_name in seen_tools:
                continue
            seen_tools.add(real_name)
            
            # Get the actual tool metadata from the registry
            try:
                tool_metadata = await self.registry.get_tool(real_name)
                logger.info(f"Retrieved tool metadata for '{real_name}': {tool_metadata}")
                
                # Try multiple ways to extract the description and input schema
                desc = None
                params = None
                
                # Check various attributes that might contain the schema
                for attr in ['description', 'desc', '_description']:
                    if hasattr(tool_metadata, attr):
                        desc = getattr(tool_metadata, attr)
                        if desc:
                            break
                
                for attr in ['inputSchema', 'input_schema', 'schema', '_input_schema', 'parameters']:
                    if hasattr(tool_metadata, attr):
                        params = getattr(tool_metadata, attr)
                        if params and params != {'type': 'object', 'properties': {}, 'required': []}:
                            break
                
                # If we still don't have them, try to get them from the tool's internal attributes
                if hasattr(tool_metadata, '__dict__'):
                    logger.info(f"Tool metadata attributes: {tool_metadata.__dict__}")
                
                # Log what we found
                logger.info(f"Extracted - desc: {desc}, params: {params}")
                
                # Fallback to defaults if still empty
                desc = desc or f"Execute {real_name}"
                params = params or {"type": "object", "properties": {}, "required": []}
                
                # Manual schema definitions for known MCP tools as fallback
                if not params or params == {"type": "object", "properties": {}, "required": []}:
                    if real_name == "tools.get_current_time":
                        desc = "Get the current time in a specific timezone"
                        params = {
                            "type": "object",
                            "properties": {
                                "timezone": {
                                    "type": "string",
                                    "description": "IANA timezone name (e.g., 'America/New_York', 'Europe/London'). If not provided, uses system timezone."
                                }
                            },
                            "required": []  # timezone is optional according to some implementations
                        }
                    elif real_name == "tools.convert_time":
                        desc = "Convert time between different timezones"
                        params = {
                            "type": "object",
                            "properties": {
                                "time": {
                                    "type": "string",
                                    "description": "Time to convert (e.g., '15:30' or '3:30 PM')"
                                },
                                "source_timezone": {
                                    "type": "string",
                                    "description": "Source IANA timezone name"
                                },
                                "target_timezone": {
                                    "type": "string",
                                    "description": "Target IANA timezone name"
                                }
                            },
                            "required": ["time", "source_timezone", "target_timezone"]
                        }
                    elif real_name == "tools.get_weather":
                        desc = "Get current weather information for a specific city"
                        params = {
                            "type": "object",
                            "properties": {
                                "city": {
                                    "type": "string",
                                    "description": "Name of the city to get weather for (e.g., 'New York', 'London', 'Tokyo')"
                                }
                            },
                            "required": ["city"]
                        }
                    elif real_name == "tools.get_weather_by_datetime_range":
                        desc = "Get weather information for a specific date range"
                        params = {
                            "type": "object",
                            "properties": {
                                "city": {
                                    "type": "string",
                                    "description": "Name of the city to get weather for"
                                },
                                "start_date": {
                                    "type": "string",
                                    "description": "Start date in YYYY-MM-DD format"
                                },
                                "end_date": {
                                    "type": "string",
                                    "description": "End date in YYYY-MM-DD format"
                                }
                            },
                            "required": ["city", "start_date", "end_date"]
                        }
                    elif real_name == "tools.get_current_datetime":
                        desc = "Get current datetime in a specific timezone"
                        params = {
                            "type": "object",
                            "properties": {
                                "timezone_name": {
                                    "type": "string",
                                    "description": "IANA timezone name (e.g., 'America/New_York', 'Europe/London'). If not provided, uses UTC."
                                }
                            },
                            "required": []
                        }
                
            except Exception as e:
                logger.warning(f"Could not get tool metadata for '{real_name}': {e}")
                desc = f"Execute {real_name}"
                params = {"type": "object", "properties": {}, "required": []}
            
            # turn "tools.get_current_time" → "tools__get_current_time"
            safe = re.sub(r"[^0-9a-zA-Z_]", "_", real_name)[:64]
            # ensure uniqueness
            if safe in self._name_map and self._name_map[safe] != real_name:
                safe = f"{safe}_{abs(hash(real_name)) & 0xFFFF:x}"
            self._name_map[safe] = real_name
            
            # Debug: Log the tool information to see what we're getting
            logger.info(f"Tool '{real_name}': desc='{desc}', params={params}")

            self.tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": safe,            # <- OpenAI-safe alias
                        "description": desc,
                        "parameters": params,
                    },
                }
            )

        logger.info("Generated %d tool schemas (alias → real): %s",
                    len(self.tools), self._name_map)

    async def _execute_tools_natively(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Translate the OpenAI-safe alias back to the real dotted name and run
        the calls through chuk-tool-processor.
        """
        if not self.executor:
            await self._initialize_tools()
        if not self.executor:
            return [
                {
                    "tool_call_id": tc.get("id"),
                    "role": "tool",
                    "name": tc.get("function", {}).get("name"),
                    "content": "Tool engine not initialised",
                }
                for tc in tool_calls
            ]

        native_calls = []
        for tc in tool_calls:
            func = tc.get("function", {})
            alias = func.get("name")
            real = self._name_map.get(alias, alias)          # fall back to alias
            
            logger.info(f"Tool call: alias='{alias}' -> real='{real}'")
            logger.info(f"Available name mappings: {self._name_map}")
            
            args = func.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"input": args}
            native_calls.append(ToolCall(tool=real, arguments=args))

        try:
            results = await self.executor.execute(native_calls)
        except Exception as exc:
            logger.exception("Native tool execution failed")
            return [
                {
                    "tool_call_id": tc.get("id"),
                    "role": "tool",
                    "name": tc.get("function", {}).get("name"),
                    "content": f"Native execution error: {exc}",
                }
                for tc in tool_calls
            ]

        formatted = []
        for tc, res in zip(tool_calls, results):
            content = (
                json.dumps(res.result, indent=2)
                if res.error is None
                else f"Error: {res.error}"
            )
            formatted.append(
                {
                    "tool_call_id": tc.get("id"),
                    "role": "tool",
                    "name": tc.get("function", {}).get("name"),
                    "content": content,
                }
            )
        return formatted

    async def generate_response(
        self, 
        messages: List[Dict[str, Any]]
    ) -> Union[AsyncGenerator[Dict[str, str], None], Dict[str, str]]:
        """
        Generate a response using the LLM with native tool calling.

        Args:
            messages: The conversation history in ChatML format

        Returns:
            Either an async generator of response chunks (if streaming and no tools)
            or a complete response (if tools used)
        """
        # Initialize LLM client
        client = get_llm_client(
            provider=self.provider,
            model=self.model,
            config=self.config
        )

        # Ensure the system message is at the beginning
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": self.instruction})

        # Initialize tools if not already done
        if self.enable_tools and not self._tools_initialized:
            await self._initialize_tools()

        has_tools = self.enable_tools and len(self.tools) > 0

        try:
            if has_tools:
                # Tool calls not supported in streaming mode (yet), always use non-streaming
                return await self._generate_with_native_tools(client, messages)
            else:
                return await client.create_completion(
                    messages=messages,
                    stream=self.streaming
                )
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise

    async def _generate_with_native_tools(self, client, messages):
        # 1️⃣ call the model → gets tool_calls
        response = await client.create_completion(
            messages=messages,
            stream=False,
            tools=self.tools,
        )

        tool_calls = response.get("tool_calls", [])
        if not tool_calls:
            return response                         # nothing to do

        # 2️⃣ execute tools
        tool_results = await self._execute_tools_natively(tool_calls)

        # 3️⃣ ask the model to wrap-up
        messages.extend([
            {
                "role": "assistant",
                "content": response.get("response", ""),
                "tool_calls": tool_calls,
            },
            *tool_results,                          # push tool outputs
        ])

        final_response = await client.create_completion(
            messages=messages,
            stream=False,
        )

        # ── NEW ───────────────────────────────────────────────────────────
        # If the wrap-up is empty, fall back to the raw tool output(s)
        if not final_response.get("response"):
            combined = "\n\n".join(
                r["content"] for r in tool_results if r.get("content")
            ) or "Tool executed but returned no text."
            final_response["response"] = combined
        # ──────────────────────────────────────────────────────────────────

        return final_response

    async def generate_summary(self, messages: List[Dict[str, Any]]) -> str:
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
        system_prompt = """
        Create a concise summary of the conversation below.
        Focus on key points and main topics of the discussion.
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
    
    async def cleanup(self) -> None:
        """Clean up native tool engine resources."""
        if self.stream_manager:
            await self.stream_manager.close()
            self.stream_manager = None
        
        self._tools_initialized = False
        logger.info("Cleaned up native tool engine resources")
    
    async def __aenter__(self):
        """Async context manager entry."""
        if self.enable_tools:
            await self._initialize_tools()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()

# Factory functions for common agent configurations
def create_agent_with_mcp(
    name: str,
    description: str = "",
    instruction: str = "",
    mcp_servers: List[str] = None,
    mcp_config_file: str = None,
    provider: str = "openai",
    model: str = "gpt-4",
    **kwargs
) -> ChukAgent:
    """
    Create a ChukAgent with MCP tools using the native tool engine.
    
    Args:
        name: Agent name
        description: Agent description
        instruction: Agent instructions
        mcp_servers: List of MCP server names
        mcp_config_file: Path to MCP configuration file
        provider: LLM provider
        model: LLM model
        **kwargs: Additional ChukAgent arguments
        
    Returns:
        Configured ChukAgent with native tool calling
    """
    return ChukAgent(
        name=name,
        description=description,
        instruction=instruction,
        provider=provider,
        model=model,
        mcp_servers=mcp_servers,
        mcp_config_file=mcp_config_file,
        enable_tools=True,
        **kwargs
    )

def create_simple_agent(
    name: str,
    description: str = "",
    instruction: str = "",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    **kwargs
) -> ChukAgent:
    """
    Create a simple ChukAgent without tools.
    
    Args:
        name: Agent name
        description: Agent description  
        instruction: Agent instructions
        provider: LLM provider
        model: LLM model
        **kwargs: Additional ChukAgent arguments
        
    Returns:
        Simple ChukAgent without tool calling
    """
    return ChukAgent(
        name=name,
        description=description,
        instruction=instruction,
        provider=provider,
        model=model,
        enable_tools=False,
        **kwargs
    )