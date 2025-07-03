#!/usr/bin/env python3
"""
Resilient A2A Agent Example
===========================

This script demonstrates a resilient A2A agent that:
1. Recovers from MCP connection failures
2. Handles agent crashes and restarts
3. Shows circuit breaker behavior
4. Demonstrates session persistence across failures
5. Includes monitoring and health checks

Usage:
    python example_resilient_agent.py
"""

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

# Configure logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FlakyMCPServer:
    """
    Simulates an MCP server that occasionally fails to demonstrate resilience.
    """
    
    def __init__(self, name: str, failure_rate: float = 0.3):
        self.name = name
        self.failure_rate = failure_rate
        self.is_connected = True
        self.call_count = 0
        
    async def list_tools(self):
        """Mock list tools that sometimes fails."""
        self.call_count += 1
        
        if random.random() < self.failure_rate:
            self.is_connected = False
            raise ConnectionError(f"MCP server {self.name} connection lost!")
        
        self.is_connected = True
        return [
            {
                "name": "weather",
                "description": "Get weather information",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"}
                    }
                }
            },
            {
                "name": "calculator",
                "description": "Perform calculations",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"}
                    }
                }
            }
        ]
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]):
        """Mock tool execution that sometimes fails."""
        if random.random() < self.failure_rate:
            raise ConnectionError(f"MCP server {self.name} lost connection during execution!")
        
        if tool_name == "weather":
            location = arguments.get("location", "Unknown")
            return f"Weather in {location}: Sunny, 22°C"
        elif tool_name == "calculator":
            expression = arguments.get("expression", "1+1")
            try:
                result = eval(expression)  # Don't do this in production!
                return f"Result: {result}"
            except:
                return "Error: Invalid expression"
        else:
            return f"Unknown tool: {tool_name}"


class ResilientChukAgent:
    """
    A ChukAgent that demonstrates resilience to various failures.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.call_count = 0
        self.failure_mode = None  # Can be set to simulate different failures
        self.mcp_server = FlakyMCPServer("demo_mcp")
        self.session_data = {}  # Simple in-memory session storage
        
    async def initialize_tools(self):
        """Initialize tools with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                tools = await self.mcp_server.list_tools()
                logger.info(f"✅ {self.name}: Tools initialized successfully (attempt {attempt + 1})")
                return tools
            except ConnectionError as e:
                logger.warning(f"⚠️ {self.name}: Tool initialization failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"❌ {self.name}: Failed to initialize tools after {max_retries} attempts")
                    return []
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]):
        """Execute tool with retry and fallback logic."""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                result = await self.mcp_server.execute_tool(tool_name, arguments)
                logger.info(f"🔧 {self.name}: Tool '{tool_name}' executed successfully")
                return result
            except ConnectionError as e:
                logger.warning(f"⚠️ {self.name}: Tool execution failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    # Fallback response
                    logger.info(f"🔄 {self.name}: Using fallback for tool '{tool_name}'")
                    return f"Tool '{tool_name}' temporarily unavailable - using cached/fallback response"
    
    async def complete(self, messages: List[Dict[str, Any]], use_tools: bool = True, session_id: Optional[str] = None):
        """
        Complete a conversation with resilience features.
        """
        self.call_count += 1
        
        # Simulate different failure modes for demonstration
        if self.failure_mode == "crash" and self.call_count % 5 == 0:
            logger.error(f"💥 {self.name}: Simulating agent crash!")
            raise RuntimeError("Agent crashed!")
        
        if self.failure_mode == "timeout" and self.call_count % 7 == 0:
            logger.warning(f"⏰ {self.name}: Simulating timeout...")
            await asyncio.sleep(10)  # This would trigger timeout
        
        # Extract user message
        user_content = "Hello"
        for msg in messages:
            if msg.get("role") == "user":
                user_content = msg.get("content", "Hello")
                break
        
        logger.info(f"🤖 {self.name}: Processing message: '{user_content[:50]}...'")
        
        # Session handling
        if session_id:
            if session_id not in self.session_data:
                self.session_data[session_id] = []
            self.session_data[session_id].append({"role": "user", "content": user_content})
        
        # Determine if we need tools
        needs_tools = use_tools and any(word in user_content.lower() for word in ["weather", "calculate", "tool"])
        
        tool_calls = []
        tool_results = []
        
        if needs_tools:
            # Initialize tools if needed
            await self.initialize_tools()
            
            # Execute tools based on content
            if "weather" in user_content.lower():
                location = "San Francisco"  # Default location
                if "in " in user_content.lower():
                    # Simple location extraction
                    parts = user_content.lower().split("in ")
                    if len(parts) > 1:
                        location = parts[1].split()[0].capitalize()
                
                tool_calls.append({
                    "id": "weather_1",
                    "function": {"name": "weather", "arguments": f'{{"location": "{location}"}}'}
                })
                
                weather_result = await self.execute_tool("weather", {"location": location})
                tool_results.append({
                    "tool_call_id": "weather_1",
                    "content": weather_result
                })
            
            if "calculate" in user_content.lower() or any(op in user_content for op in ["+", "-", "*", "/"]):
                # Simple expression extraction
                expression = "2+2"  # Default
                if "calculate" in user_content.lower():
                    parts = user_content.lower().split("calculate")
                    if len(parts) > 1:
                        expression = parts[1].strip()
                
                tool_calls.append({
                    "id": "calc_1", 
                    "function": {"name": "calculator", "arguments": f'{{"expression": "{expression}"}}'}
                })
                
                calc_result = await self.execute_tool("calculator", {"expression": expression})
                tool_results.append({
                    "tool_call_id": "calc_1",
                    "content": calc_result
                })
        
        # Generate response
        if tool_results:
            response_content = f"I used tools to help you:\n"
            for result in tool_results:
                response_content += f"- {result['content']}\n"
        else:
            response_content = f"Hello! I'm {self.name}. I received your message: '{user_content}'. I can help with weather queries and calculations using my tools!"
        
        # Store response in session
        if session_id:
            self.session_data[session_id].append({"role": "assistant", "content": response_content})
        
        return {
            "content": response_content,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "usage": {"total_tokens": len(response_content) + len(user_content)}
        }
    
    async def get_conversation_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get conversation history for session."""
        return self.session_data.get(session_id, [])
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get agent health status."""
        return {
            "agent_name": self.name,
            "status": "healthy" if self.failure_mode != "crash" else "degraded",
            "call_count": self.call_count,
            "mcp_connected": self.mcp_server.is_connected,
            "mcp_calls": self.mcp_server.call_count,
            "active_sessions": len(self.session_data),
            "failure_mode": self.failure_mode
        }


class ResilientAgentDemo:
    """
    Demonstrates the resilient agent in action.
    """
    
    def __init__(self):
        self.agent = ResilientChukAgent("DemoAgent")
        self.session_id = "demo_session_123"
        
    async def demonstrate_basic_functionality(self):
        """Show basic agent functionality."""
        print("\n" + "="*60)
        print("🚀 BASIC FUNCTIONALITY DEMO")
        print("="*60)
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant with tools."},
            {"role": "user", "content": "Hello! Can you tell me about yourself?"}
        ]
        
        result = await self.agent.complete(messages, session_id=self.session_id)
        print(f"Agent Response: {result['content']}")
        print(f"Health Status: {self.agent.get_health_status()}")
    
    async def demonstrate_tool_usage(self):
        """Show tool usage with potential MCP failures."""
        print("\n" + "="*60)
        print("🔧 TOOL USAGE WITH MCP RESILIENCE DEMO")
        print("="*60)
        
        # Test weather tool
        messages = [
            {"role": "user", "content": "What's the weather like in New York?"}
        ]
        
        for attempt in range(3):
            try:
                print(f"\nAttempt {attempt + 1}: Weather query")
                result = await self.agent.complete(messages, session_id=self.session_id)
                print(f"✅ Success: {result['content']}")
                break
            except Exception as e:
                print(f"❌ Failed: {e}")
                await asyncio.sleep(1)
        
        # Test calculator tool
        messages = [
            {"role": "user", "content": "Calculate 15 * 23 + 7"}
        ]
        
        for attempt in range(3):
            try:
                print(f"\nAttempt {attempt + 1}: Calculator query")
                result = await self.agent.complete(messages, session_id=self.session_id)
                print(f"✅ Success: {result['content']}")
                break
            except Exception as e:
                print(f"❌ Failed: {e}")
                await asyncio.sleep(1)
    
    async def demonstrate_agent_crashes(self):
        """Show agent crash recovery."""
        print("\n" + "="*60)
        print("💥 AGENT CRASH RECOVERY DEMO")
        print("="*60)
        
        # Enable crash mode
        self.agent.failure_mode = "crash"
        
        messages = [
            {"role": "user", "content": "Tell me a joke"}
        ]
        
        for i in range(10):
            try:
                print(f"\nRequest {i + 1}")
                result = await self.agent.complete(messages, session_id=self.session_id)
                print(f"✅ Success: {result['content'][:100]}...")
            except RuntimeError as e:
                print(f"💥 Agent crashed: {e}")
                print("🔄 Simulating agent restart...")
                # In real system, this would be handled by the handler
                self.agent = ResilientChukAgent("DemoAgent-Restarted")
                self.agent.failure_mode = "crash"  # Keep crash mode for demo
                await asyncio.sleep(1)
            
            await asyncio.sleep(0.5)
        
        # Disable crash mode
        self.agent.failure_mode = None
    
    async def demonstrate_session_persistence(self):
        """Show session persistence across failures."""
        print("\n" + "="*60)
        print("💾 SESSION PERSISTENCE DEMO")
        print("="*60)
        
        # Build up conversation history
        conversation_steps = [
            "My name is Alice",
            "I live in San Francisco", 
            "I work as a software engineer",
            "What's the weather like where I live?"
        ]
        
        for step in conversation_steps:
            messages = [{"role": "user", "content": step}]
            result = await self.agent.complete(messages, session_id=self.session_id)
            print(f"User: {step}")
            print(f"Agent: {result['content'][:100]}...")
            
            # Show session history
            history = await self.agent.get_conversation_history(self.session_id)
            print(f"Session has {len(history)} messages")
            print()
    
    async def demonstrate_health_monitoring(self):
        """Show health monitoring capabilities."""
        print("\n" + "="*60)
        print("🏥 HEALTH MONITORING DEMO")
        print("="*60)
        
        # Monitor health over several interactions
        for i in range(5):
            messages = [{"role": "user", "content": f"Health check {i + 1}"}]
            
            try:
                await self.agent.complete(messages)
                health = self.agent.get_health_status()
                print(f"Health Check {i + 1}: {health}")
            except Exception as e:
                print(f"Health Check {i + 1}: ERROR - {e}")
            
            await asyncio.sleep(1)
    
    async def demonstrate_circuit_breaker(self):
        """Show circuit breaker behavior."""
        print("\n" + "="*60)
        print("⚡ CIRCUIT BREAKER SIMULATION DEMO")
        print("="*60)
        
        print("This would typically be handled by the ResilientHandler wrapper")
        print("Circuit breaker opens after repeated failures and closes after recovery")
        
        # Simulate high failure rate
        original_failure_rate = self.agent.mcp_server.failure_rate
        self.agent.mcp_server.failure_rate = 0.8  # 80% failure rate
        
        print(f"Setting MCP failure rate to {self.agent.mcp_server.failure_rate * 100}%")
        
        success_count = 0
        failure_count = 0
        
        for i in range(10):
            try:
                await self.agent.initialize_tools()
                success_count += 1
                print(f"Attempt {i + 1}: ✅ Success")
            except:
                failure_count += 1
                print(f"Attempt {i + 1}: ❌ Failed")
            
            await asyncio.sleep(0.5)
        
        print(f"Results: {success_count} successes, {failure_count} failures")
        print("In production, circuit breaker would open after threshold failures")
        
        # Restore normal failure rate
        self.agent.mcp_server.failure_rate = original_failure_rate
    
    async def run_full_demo(self):
        """Run the complete resilience demonstration."""
        print("🎭 A2A RESILIENT AGENT DEMONSTRATION")
        print("This demo shows how A2A agents handle various failure scenarios")
        
        await self.demonstrate_basic_functionality()
        await self.demonstrate_tool_usage()
        await self.demonstrate_session_persistence()
        await self.demonstrate_health_monitoring()
        await self.demonstrate_circuit_breaker()
        await self.demonstrate_agent_crashes()
        
        print("\n" + "="*60)
        print("🎉 DEMO COMPLETED")
        print("="*60)
        print("Key resilience features demonstrated:")
        print("✅ MCP connection recovery with exponential backoff")
        print("✅ Tool execution fallbacks when MCP unavailable")
        print("✅ Agent crash recovery (handled by ResilientHandler)")
        print("✅ Session persistence across failures")
        print("✅ Health monitoring and status reporting")
        print("✅ Circuit breaker pattern simulation")
        print("\nIn production, these features work together to provide")
        print("highly available AI agents that gracefully handle failures.")


async def main():
    """Run the resilient agent demonstration."""
    demo = ResilientAgentDemo()
    await demo.run_full_demo()


if __name__ == "__main__":
    # Run the demonstration
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Demo interrupted by user")
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        logger.exception("Demo error:")