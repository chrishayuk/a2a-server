#!/usr/bin/env python3
"""
Standalone ChukAgent Test Script
================================

Test ChukAgent directly without A2A framework to isolate issues.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Loaded .env file")
except ImportError:
    print("ℹ dotenv not available, using system environment variables")
except Exception as e:
    print(f"ℹ Could not load .env: {e}")

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Quiet some noisy loggers
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def test_basic_chuk_agent():
    """Test a basic ChukAgent without MCP tools."""
    print("\n" + "="*60)
    print("Testing Basic ChukAgent (No MCP Tools)")
    print("="*60)
    
    try:
        from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
        
        # Create a simple agent without MCP tools
        agent = ChukAgent(
            name="test_agent",
            provider="openai",
            model="gpt-4o-mini",
            description="Simple test agent",
            instruction="You are a helpful AI assistant. Always respond clearly and concisely.",
            enable_sessions=False,  # Disable sessions for simplicity
            mcp_servers=[],  # No MCP tools
            mcp_config_file=None
        )
        
        print(f"✓ Agent created: {agent.name}")
        print(f"✓ Provider: {agent.provider}")
        print(f"✓ Model: {agent.model}")
        print(f"✓ Sessions enabled: {agent.enable_sessions}")
        
        # Test environment
        api_key = os.getenv('OPENAI_API_KEY')
        print(f"✓ OpenAI API Key: {'SET' if api_key else 'NOT SET'}")
        if not api_key:
            print("❌ Error: OPENAI_API_KEY environment variable not set!")
            return False
        
        # Test system prompt
        system_prompt = agent.get_system_prompt()
        print(f"✓ System prompt: {system_prompt[:100]}...")
        
        # Test LLM client creation
        print("\n--- Testing LLM Client ---")
        llm_client = await agent.get_llm_client()
        print(f"✓ LLM client created: {type(llm_client)}")
        
        # Test direct LLM call
        print("\n--- Testing Direct LLM Call ---")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Say 'Hello World' and tell me what 2+2 equals."}
        ]
        
        response = await llm_client.create_completion(messages=messages)
        print(f"✓ Raw response type: {type(response)}")
        print(f"✓ Raw response: {response}")
        
        # Test response extraction
        extracted = agent._extract_response_content(response)
        print(f"✓ Extracted content: '{extracted}'")
        
        # Test complete method
        print("\n--- Testing Complete Method ---")
        result = await agent.complete(messages, use_tools=False)
        print(f"✓ Complete result: {result}")
        print(f"✓ Complete content: '{result.get('content', 'NO CONTENT')}'")
        
        # Test chat method
        print("\n--- Testing Chat Method ---")
        chat_response = await agent.chat("What is the capital of France?")
        print(f"✓ Chat response: '{chat_response}'")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in basic test: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_chuk_agent_with_mcp():
    """Test ChukAgent with MCP tools."""
    print("\n" + "="*60)
    print("Testing ChukAgent with MCP Tools")
    print("="*60)
    
    try:
        from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
        
        # Create MCP configuration for time tools
        config_file = "test_time_config.json"
        config = {
            "mcpServers": {
                "time": {
                    "command": "uvx",
                    "args": ["mcp-server-time", "--local-timezone=America/New_York"]
                }
            }
        }
        
        # Write config file
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"✓ Created MCP config: {config_file}")
        
        # Create agent with MCP tools
        agent = ChukAgent(
            name="time_agent",
            provider="openai",
            model="gpt-4o-mini",
            description="Time agent with MCP tools",
            instruction="You are a helpful time assistant. Use your time tools to provide accurate time information.",
            mcp_transport="stdio",
            mcp_config_file=config_file,
            mcp_servers=["time"],
            namespace="stdio",
            enable_sessions=False
        )
        
        print(f"✓ Agent created with MCP: {agent.name}")
        
        # Test tool initialization
        print("\n--- Testing Tool Initialization ---")
        await agent.initialize_tools()
        
        if agent._tools_initialized:
            print("✓ Tools initialized successfully")
            
            # Get available tools
            tools = await agent.get_available_tools()
            print(f"✓ Available tools: {tools}")
            
            # Test with tools
            print("\n--- Testing Chat with Tools ---")
            response = await agent.chat("What time is it in New York right now?")
            print(f"✓ Tool-enabled response: '{response}'")
            
        else:
            print("❌ Tools failed to initialize")
            print("This might be because mcp-server-time is not installed.")
            print("Install with: uvx install mcp-server-time")
            
        # Clean up
        Path(config_file).unlink(missing_ok=True)
        return True
        
    except Exception as e:
        print(f"❌ Error in MCP test: {e}")
        import traceback
        traceback.print_exc()
        # Clean up
        Path("test_time_config.json").unlink(missing_ok=True)
        return False

async def test_existing_agents():
    """Test the existing sample agents."""
    print("\n" + "="*60)
    print("Testing Existing Sample Agents")
    print("="*60)
    
    # Test time agent
    try:
        print("\n--- Testing time_agent ---")
        from a2a_server.sample_agents.time_agent import time_agent
        print(f"✓ time_agent loaded: {type(time_agent)}")
        print(f"✓ time_agent name: {time_agent.name}")
        
        response = await time_agent.chat("What time is it?", session_id="test-session")
        print(f"✓ time_agent response: '{response}'")
        
    except Exception as e:
        print(f"❌ time_agent error: {e}")
    
    # Test chef agent
    try:
        print("\n--- Testing chef_agent ---")
        from a2a_server.sample_agents.chuk_chef import chef_agent
        print(f"✓ chef_agent loaded: {type(chef_agent)}")
        print(f"✓ chef_agent name: {chef_agent.name}")
        
        response = await chef_agent.chat("Give me a quick recipe for scrambled eggs", session_id="test-session")
        print(f"✓ chef_agent response: '{response[:200]}...'")
        
    except Exception as e:
        print(f"❌ chef_agent error: {e}")
    
    # Test weather agent
    try:
        print("\n--- Testing weather_agent ---")
        from a2a_server.sample_agents.weather_agent import weather_agent
        print(f"✓ weather_agent loaded: {type(weather_agent)}")
        print(f"✓ weather_agent name: {weather_agent.name}")
        
        response = await weather_agent.chat("What's the weather like?", session_id="test-session")
        print(f"✓ weather_agent response: '{response}'")
        
    except Exception as e:
        print(f"❌ weather_agent error: {e}")

async def main():
    """Run all tests."""
    print("ChukAgent Standalone Test Suite")
    print("="*60)
    
    # Environment check
    print("\n--- Environment Check ---")
    api_key = os.getenv('OPENAI_API_KEY')
    print(f"OPENAI_API_KEY: {'SET' if api_key else 'NOT SET'}")
    
    if not api_key:
        print("\n❌ CRITICAL: OPENAI_API_KEY not set!")
        print("Please set it with: export OPENAI_API_KEY='your-key-here'")
        return
    
    # Run tests
    tests = [
        ("Basic ChukAgent", test_basic_chuk_agent),
        ("ChukAgent with MCP", test_chuk_agent_with_mcp),
        ("Existing Sample Agents", test_existing_agents)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            print(f"\n{'='*20} {test_name} {'='*20}")
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"❌ Test '{test_name}' failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for test_name, success in results:
        status = "✓ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
    
    total_tests = len(results)
    passed_tests = sum(1 for _, success in results if success)
    print(f"\nPassed: {passed_tests}/{total_tests}")

if __name__ == "__main__":
    asyncio.run(main())