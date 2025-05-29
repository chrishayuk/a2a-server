# a2a_server/tasks/handlers/chuk/chuk_agent.py
"""
ChukAgent: A pure agent abstraction with chuk-tool-processor as the native tool calling engine
"""
import asyncio
import json
import logging
import re
from typing import Dict, List, Any, Optional, Union, AsyncGenerator
from pathlib import Path

# a2a imports
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

# chuk-llm imports
from chuk_llm.llm.llm_client import get_llm_client
from chuk_llm.llm.configuration.provider_config import ProviderConfig

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
        enable_tools: bool = True,
        token_threshold: int = 4000,
        summarization_strategy: str = "key_points",
        enable_memory: bool = True
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
            token_threshold: Maximum tokens before session segmentation
            summarization_strategy: Strategy for summarizing sessions
            enable_memory: Whether to enable conversation memory
        """
        self.name = name
        self.description = description
        
        # Define a default instruction if none is provided
        default_instruction = f"You are a helpful assistant named {name}. {description}"
        
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
        
        # Session management (simplified)
        self.token_threshold = token_threshold
        self.summarization_strategy = summarization_strategy
        self.enable_memory = enable_memory
        
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

        # First, get the actual tool schemas from the MCP server
        mcp_tool_schemas = {}
        if self.stream_manager:
            try:
                # Try to get the tools directly from the stream manager
                if hasattr(self.stream_manager, 'list_tools'):
                    # list_tools needs a server name - try with our known server names
                    for server_name in self.mcp_servers:
                        try:
                            mcp_tools = await self.stream_manager.list_tools(server_name)
                            logger.info(f"MCP tools from server '{server_name}': {mcp_tools}")
                            for tool in mcp_tools:
                                if hasattr(tool, 'name'):
                                    mcp_tool_schemas[tool.name] = {
                                        'description': getattr(tool, 'description', None),
                                        'inputSchema': getattr(tool, 'inputSchema', None)
                                    }
                                elif isinstance(tool, dict):
                                    tool_name = tool.get('name')
                                    if tool_name:
                                        mcp_tool_schemas[tool_name] = {
                                            'description': tool.get('description'),
                                            'inputSchema': tool.get('inputSchema')
                                        }
                        except Exception as e:
                            logger.debug(f"Could not get tools from server '{server_name}': {e}")
                
                # Alternative: try to access server instances directly
                elif hasattr(self.stream_manager, '_servers'):
                    for server_id, server in self.stream_manager._servers.items():
                        if hasattr(server, 'list_tools'):
                            try:
                                tools_response = await server.list_tools()
                                if hasattr(tools_response, 'tools'):
                                    for tool in tools_response.tools:
                                        mcp_tool_schemas[tool.name] = {
                                            'description': tool.description,
                                            'inputSchema': tool.inputSchema
                                        }
                                logger.info(f"Got {len(mcp_tool_schemas)} tool schemas from MCP server")
                            except Exception as e:
                                logger.debug(f"Could not get tools from server {server_id}: {e}")
                
                logger.info(f"Extracted MCP tool schemas: {mcp_tool_schemas}")
            except Exception as e:
                logger.warning(f"Could not extract MCP tool schemas: {e}")

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
                        # Accept tools from our specific namespace or default namespace
                        if namespace == self.tool_namespace or namespace == "default" or namespace is None:
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
                
                # First, check if we have MCP schemas for this tool
                if hasattr(tool_metadata, 'tool_name') and tool_metadata.tool_name in mcp_tool_schemas:
                    schema = mcp_tool_schemas[tool_metadata.tool_name]
                    desc = schema.get('description')
                    params = schema.get('inputSchema')
                    logger.info(f"Found MCP schema for {tool_metadata.tool_name}: desc={desc}, params={params}")
                
                # Fallback: try to extract from tool metadata attributes
                if not desc:
                    for attr in ['description', 'desc', '_description']:
                        if hasattr(tool_metadata, attr):
                            desc = getattr(tool_metadata, attr)
                            if desc:
                                break
                
                if not params:
                    for attr in ['inputSchema', 'input_schema', 'schema', '_input_schema', 'parameters']:
                        if hasattr(tool_metadata, attr):
                            params = getattr(tool_metadata, attr)
                            if params and params != {'type': 'object', 'properties': {}, 'required': []}:
                                break
                
                # Log what we found
                logger.info(f"Extracted - desc: {desc}, params: {params}")
                
                # Fallback to defaults if still empty
                desc = desc or f"Execute {real_name}"
                params = params or {"type": "object", "properties": {}, "required": []}
                
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
            logger.info(f"Tool execution results: {[{'result': r.result, 'error': r.error} for r in results]}")
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
            logger.info(f"Formatted tool result: {formatted[-1]}")
        return formatted

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
        Process a message and generate responses - FIXED to emit tool artifacts.
        """
        # Clear any previous tool responses
        self._tool_responses = []
        
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
        
        # Format messages for the LLM
        llm_messages = [
            {"role": "system", "content": self.instruction},
            {"role": "user", "content": user_content_str}
        ]
        
        # Track response state
        started_generating = False
        full_response = ""
        
        try:
            # Use generate_response which handles tool calling
            # Don't await it - it might return an async generator
            response_generator = self.generate_response(llm_messages)
            
            # If it's a coroutine, await it first
            if hasattr(response_generator, '__await__'):
                response_generator = await response_generator
            
            # Check if it's an async generator (streaming) or a direct response (tools)
            if hasattr(response_generator, "__aiter__"):
                # Streaming case
                async for chunk in response_generator:
                    delta = chunk.get("response", "")
                    if delta:
                        full_response += delta
                        
                        artifact = Artifact(
                            name=f"{self.name}_response",
                            parts=[TextPart(type="text", text=delta if not started_generating else full_response)],
                            index=0
                        )
                        
                        started_generating = True
                        yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
                        await asyncio.sleep(0.01)
            else:
                # Non-streaming response (e.g. from tool calls)
                if isinstance(response_generator, dict):
                    text_response = response_generator.get("response", "")
                    if not text_response:
                        if "tool_calls" in response_generator:
                            text_response = "Tool executed but returned no direct response."
                        else:
                            text_response = str(response_generator)
                else:
                    text_response = str(response_generator)

                full_response = text_response

                yield TaskArtifactUpdateEvent(
                    id=task_id,
                    artifact=Artifact(
                        name=f"{self.name}_response",
                        parts=[TextPart(type="text", text=text_response or "")],
                        index=0
                    )
                )
            
            # NEW: Emit tool response artifacts if any tools were called
            if hasattr(self, '_tool_responses') and self._tool_responses:
                logger.info(f"Emitting {len(self._tool_responses)} tool response artifacts")
                for i, tool_response in enumerate(self._tool_responses):
                    yield TaskArtifactUpdateEvent(
                        id=task_id,
                        artifact=Artifact(
                            name=f"{self.name}_tool_response_{i}",
                            parts=[TextPart(type="text", text=tool_response)],
                            index=i + 1
                        )
                    )
            
            # Complete the task
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.completed),
                final=True
            )
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            yield TaskStatusUpdateEvent(
                id=task_id,
                status=TaskStatus(state=TaskState.failed),
                final=True
            )
            yield TaskArtifactUpdateEvent(
                id=task_id,
                artifact=Artifact(
                    name=f"{self.name}_error",
                    parts=[TextPart(type="text", text=f"Error: {str(e)}")],
                    index=0
                )
            )
            
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
                # No tools - return the async generator directly (don't await it)
                return client.create_completion(
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

        logger.info(f"LLM requested {len(tool_calls)} tool calls: {[tc.get('function', {}).get('name') for tc in tool_calls]}")

        # 2️⃣ execute tools
        tool_results = await self._execute_tools_natively(tool_calls)
        
        # Log the tool results for debugging
        for i, result in enumerate(tool_results):
            logger.info(f"Tool result {i}: {result}")
            
            # NEW: Store tool results for artifact emission
            if not hasattr(self, '_tool_responses'):
                self._tool_responses = []
            self._tool_responses.append(result.get("content", ""))

        # 3️⃣ ask the model to wrap-up
        messages.extend([
            {
                "role": "assistant",
                "content": response.get("response", ""),
                "tool_calls": tool_calls,
            },
            *tool_results,                          # push tool outputs
        ])

        logger.info(f"Messages before final LLM call: {json.dumps(messages, indent=2)}")

        final_response = await client.create_completion(
            messages=messages,
            stream=False,
        )

        logger.info(f"Final LLM response: {final_response}")

        # ── NEW ───────────────────────────────────────────────────────────
        # If the wrap-up is empty, fall back to the raw tool output(s)
        if not final_response.get("response"):
            combined = "\n\n".join(
                r["content"] for r in tool_results if r.get("content")
            ) or "Tool executed but returned no text."
            final_response["response"] = combined
            logger.info(f"Used fallback response: {final_response['response']}")
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
    tool_namespace: str = None,  # Allow None to auto-generate
    provider: str = "openai",
    model: str = "gpt-4o-mini",
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
        tool_namespace: Namespace for tools in the registry (auto-generated if None)
        provider: LLM provider
        model: LLM model
        **kwargs: Additional ChukAgent arguments
        
    Returns:
        Configured ChukAgent with native tool calling
    """
    # Auto-generate unique namespace if not provided
    if tool_namespace is None:
        tool_namespace = f"{name}_tools"
    
    return ChukAgent(
        name=name,
        description=description,
        instruction=instruction,
        provider=provider,
        model=model,
        mcp_servers=mcp_servers,
        mcp_config_file=mcp_config_file,
        tool_namespace=tool_namespace,
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