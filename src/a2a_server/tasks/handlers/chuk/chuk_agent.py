"""
ChukAgent: A pure agent abstraction focused solely on agent capabilities
"""
import logging
from typing import Dict, List, Any, Optional, Union, AsyncGenerator

# chuk-llm imports
from chuk_llm.llm.llm_client import get_llm_client
from chuk_llm.llm.provider_config import ProviderConfig

logger = logging.getLogger(__name__)

class ChukAgent:
    """
    A pure agent abstraction that focuses solely on agent capabilities.
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        instruction: str = "",
        provider: str = "openai",
        model: Optional[str] = None,
        streaming: bool = True,
        tools: Optional[List[Dict]] = None,
        tool_handlers: Optional[Dict[str, callable]] = None,
        config: Optional[ProviderConfig] = None,
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
            tools: Optional list of tool definitions
            tool_handlers: Optional map of tool name to handler function
            config: Optional provider configuration
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
        self.tools = tools or []
        self.tool_handlers = tool_handlers or {}
        self.config = config or ProviderConfig()
        
        logger.info(f"Initialized agent '{name}' using {provider}/{model or 'default'}")
    
    async def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """
        Execute a tool with the given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments to pass to the tool
            
        Returns:
            The tool execution result
            
        Raises:
            ValueError: If the tool is not found
        """
        if tool_name not in self.tool_handlers:
            raise ValueError(f"Tool '{tool_name}' not found")
            
        handler = self.tool_handlers[tool_name]
        return await handler(**tool_args)
    
    async def generate_response(
        self, 
        messages: List[Dict[str, Any]]
    ) -> Union[AsyncGenerator[Dict[str, str], None], Dict[str, str]]:
        """
        Generate a response using the LLM.
        
        Args:
            messages: The conversation history in ChatML format
            
        Returns:
            Either an async generator of response chunks (if streaming)
            or a complete response
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
        
        # Check for tool integrations
        has_tools = bool(self.tools) and bool(self.tool_handlers)
        
        # Generate response with or without tools
        try:
            if has_tools:
                return await self._generate_with_tools(client, messages)
            elif self.streaming:
                # Streaming mode
                return client.create_completion(
                    messages=messages,
                    stream=True
                )
            else:
                # Non-streaming mode
                return await client.create_completion(
                    messages=messages,
                    stream=False
                )
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise
    
    async def _generate_with_tools(self, client, messages: List[Dict[str, Any]]):
        """
        Generate a response with tool calling capabilities.
        
        Args:
            client: The LLM client
            messages: The conversation history
            
        Returns:
            The complete response with tool execution results
        """
        # Generate initial response with tools
        response = await client.create_completion(
            messages=messages,
            stream=False,
            tools=self.tools
        )
        
        # Check for tool calls
        tool_calls = response.get("tool_calls", [])
        
        if not tool_calls:
            # No tool calls, return the response directly
            return response
        
        # Execute tool calls and augment messages
        for tool_call in tool_calls:
            try:
                tool_name = tool_call.get("function", {}).get("name")
                tool_args = tool_call.get("function", {}).get("arguments", {})
                
                # Convert string arguments to dict if needed
                if isinstance(tool_args, str):
                    import json
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_args = {"text": tool_args}
                
                # Execute the tool
                result = await self._execute_tool(tool_name, tool_args)
                
                # Add tool call and result to messages
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call]
                })
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "name": tool_name,
                    "content": str(result)
                })
            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}': {e}")
                # Add error message for the tool call
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "name": tool_name,
                    "content": f"Error: {str(e)}"
                })
        
        # Generate final response with tool results
        return await client.create_completion(
            messages=messages,
            stream=False
        )