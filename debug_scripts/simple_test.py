# debug_scripts/simple_test.py
"""
Simple test to verify the ChukAgent fix is working.
"""
import asyncio
from a2a_server.sample_agents.time_agent import time_agent

async def simple_test():
    """Simple test of the working ChukAgent."""
    print("🔧 Simple ChukAgent Test")
    print("=" * 40)
    
    # Initialize agent
    await time_agent.initialize_tools()
    
    # Test schema generation directly
    print("Testing schema generation...")
    schemas = await time_agent.generate_tools_schema()
    print(f"Generated {len(schemas)} schemas")
    
    if schemas:
        for i, schema in enumerate(schemas):
            print(f"Schema {i+1}: {schema['function']['name']}")
            print(f"  Description: {schema['function']['description']}")
            print(f"  Parameters: {list(schema['function']['parameters'].get('properties', {}).keys())}")
    else:
        print("❌ No schemas generated")
        return
    
    # Test complete method
    print("\nTesting complete method...")
    result = await time_agent.complete([
        {"role": "system", "content": time_agent.get_system_prompt()},
        {"role": "user", "content": "What time is it in New York?"}
    ], use_tools=True)
    
    print(f"✅ Result: {result['content']}")
    print(f"Tool calls: {len(result['tool_calls'])}")
    print(f"Tool results: {len(result['tool_results'])}")

if __name__ == "__main__":
    asyncio.run(simple_test())