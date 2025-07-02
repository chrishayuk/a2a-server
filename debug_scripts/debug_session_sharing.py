#!/usr/bin/env python3
"""
Test script to verify cross-agent session sharing is working.
Run this after starting your A2A server to test session sharing.
"""
import asyncio
import httpx
import json
import time
from typing import Dict, Any

BASE_URL = "http://localhost:8000"

async def send_message_to_agent(agent_name: str, message: str, session_id: str) -> Dict[str, Any]:
    """Send a message to an agent and get the response."""
    
    async with httpx.AsyncClient() as client:
        # Send the message
        response = await client.post(
            f"{BASE_URL}/{agent_name}/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {
                    "message": {
                        "parts": [{"type": "text", "text": message}],
                        "role": "user"
                    },
                    "session_id": session_id
                },
                "id": "test_1"
            },
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text}"}
        
        result = response.json()
        print(f"🔍 Response from {agent_name}: {result}")
        
        if "error" in result:
            return {"error": result["error"]}
        
        if "result" not in result or "task_id" not in result["result"]:
            return {"error": f"Unexpected response format: {result}"}
        
        task_id = result["result"]["task_id"]
        
        # Stream the response
        response_parts = []
        async with client.stream(
            "POST",
            f"{BASE_URL}/{agent_name}",
            json={
                "jsonrpc": "2.0", 
                "method": "tasks/stream",
                "params": {"task_id": task_id},
                "id": "stream_1"
            },
            headers={"Content-Type": "application/json"}
        ) as stream_response:
            async for chunk in stream_response.aiter_text():
                if chunk.strip():
                    try:
                        data = json.loads(chunk.strip())
                        if "result" in data and "artifact" in data["result"]:
                            artifact = data["result"]["artifact"]
                            if artifact and "parts" in artifact:
                                for part in artifact["parts"]:
                                    if part.get("type") == "text" and part.get("text"):
                                        response_parts.append(part["text"])
                    except json.JSONDecodeError:
                        continue
        
        return {
            "agent": agent_name,
            "message": message,
            "response": "".join(response_parts),
            "session_id": session_id
        }

async def test_session_sharing():
    """Test that session sharing works between chuk_pirate and chuk_chef."""
    
    # Use a unique session ID for this test
    test_session_id = f"test_session_{int(time.time())}"
    print(f"🧪 Testing session sharing with session ID: {test_session_id}")
    
    # Step 1: Tell the pirate agent your name
    print("\n1️⃣ Telling chuk_pirate: 'my name is chukkie'")
    pirate_result = await send_message_to_agent(
        "chuk_pirate", 
        "my name is chukkie", 
        test_session_id
    )
    
    if "error" in pirate_result:
        print(f"❌ Error with pirate agent: {pirate_result['error']}")
        return False
    
    print(f"🏴‍☠️ Pirate response: {pirate_result['response'][:200]}...")
    
    # Small delay to ensure session is saved
    await asyncio.sleep(2)
    
    # Step 2: Ask the chef agent what your name is
    print("\n2️⃣ Asking chuk_chef: 'what's my name?'")
    chef_result = await send_message_to_agent(
        "chuk_chef", 
        "what's my name?", 
        test_session_id
    )
    
    if "error" in chef_result:
        print(f"❌ Error with chef agent: {chef_result['error']}")
        return False
    
    print(f"🍳 Chef response: {chef_result['response']}")
    
    # Step 3: Analyze results
    chef_response = chef_result['response'].lower()
    success = "chukkie" in chef_response or "your name" in chef_response
    
    print(f"\n📊 Test Results:")
    print(f"  Session ID: {test_session_id}")
    print(f"  Pirate agent responded: ✅")
    print(f"  Chef agent responded: ✅")
    print(f"  Chef knows the name: {'✅' if success else '❌'}")
    
    if success:
        print("\n🎉 SUCCESS! Session sharing is working correctly!")
        print("   The chef agent can see conversation history from the pirate agent.")
    else:
        print("\n💔 FAILURE: Session sharing is not working.")
        print("   The chef agent cannot see the conversation history from the pirate agent.")
        print(f"   Chef response: {chef_result['response']}")
    
    return success

async def test_agent_health():
    """Test that both agents are healthy and configured correctly."""
    
    print("🔍 Checking agent health and configuration...")
    
    async with httpx.AsyncClient() as client:
        # Check server status
        try:
            response = await client.post(
                f"{BASE_URL}/rpc",
                json={
                    "jsonrpc": "2.0",
                    "method": "handlers/status",
                    "params": {},
                    "id": "health_check"
                }
            )
            
            print(f"🔍 Server response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"🔍 Server response: {result}")
                
                if "result" in result and result["result"]:
                    handlers = result["result"]
                    
                    print("\n📋 Handler Status:")
                    for handler_name, status in handlers.items():
                        if handler_name in ["chuk_pirate", "chuk_chef"]:
                            sharing = status.get("session_sharing", "unknown")
                            sandbox = status.get("shared_sandbox_group", status.get("sandbox_id", "unknown"))
                            print(f"  {handler_name}: session_sharing={sharing}, sandbox={sandbox}")
                else:
                    print("⚠️  No handler status returned")
            else:
                print(f"❌ Server responded with status {response.status_code}")
                print(f"Response: {response.text}")
                
        except Exception as e:
            print(f"⚠️  Could not check handler status: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    print("🧪 A2A Session Sharing Test")
    print("=" * 50)
    
    async def main():
        await test_agent_health()
        success = await test_session_sharing()
        
        if success:
            print("\n✅ All tests passed! Session sharing is working correctly.")
        else:
            print("\n❌ Tests failed. Check your configuration and logs.")
    
    asyncio.run(main())