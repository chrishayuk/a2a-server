#!/usr/bin/env python3
"""
Debug script to test streaming artifacts from the A2A server.

This script will help identify where artifacts are being lost in the streaming pipeline.
"""

import asyncio
import aiohttp
import json
import sys

async def test_streaming_artifacts():
    """Test the time_ticker handler streaming behavior."""
    
    base_url = "http://localhost:8000"
    
    # Step 1: Create a task
    print("🔹 Creating task with time_ticker handler...")
    
    create_payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Start time ticker test"}]
            },
            "handler": "time_ticker"
        },
        "id": 1
    }
    
    async with aiohttp.ClientSession() as session:
        # Create task
        async with session.post(f"{base_url}/rpc", json=create_payload) as resp:
            if resp.status != 200:
                print(f"❌ Failed to create task: {resp.status}")
                return
            
            result = await resp.json()
            print(f"🔍 Raw response: {result}")
            
            # Check for actual RPC errors (not None)
            if "error" in result and result["error"] is not None:
                print(f"❌ RPC Error: {result['error']}")
                return
                
            if "result" not in result:
                print(f"❌ No result in response: {result}")
                return
                
            task_data = result["result"]
            if "id" not in task_data:
                print(f"❌ No task ID in result: {task_data}")
                return
                
            task_id = task_data["id"]
            print(f"✅ Created task: {task_id}")
        
        # Step 2: Stream events via SSE
        print("🔹 Starting SSE stream...")
        
        sse_url = f"{base_url}/events?task_ids={task_id}"
        artifact_count = 0
        
        try:
            async with session.get(sse_url) as resp:
                if resp.status != 200:
                    print(f"❌ Failed to connect to SSE: {resp.status}")
                    return
                
                print("✅ Connected to SSE stream")
                
                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith('data: '):
                        try:
                            # Parse JSON-RPC format
                            data = json.loads(line[6:])  # Remove 'data: ' prefix
                            
                            if data.get('method') == 'tasks/event':
                                params = data.get('params', {})
                                event_type = params.get('type', 'unknown')
                                event_id = params.get('id', 'unknown')
                                
                                if event_type == 'artifact':
                                    artifact_count += 1
                                    artifact = params.get('artifact', {})
                                    artifact_name = artifact.get('name', 'unknown')
                                    artifact_index = artifact.get('index', 'unknown')
                                    
                                    # Extract text from parts
                                    parts = artifact.get('parts', [])
                                    text = ""
                                    for part in parts:
                                        if part.get('type') == 'text':
                                            text = part.get('text', '')
                                            break
                                    
                                    print(f"📨 Artifact {artifact_count}: {artifact_name}[{artifact_index}] - {text}")
                                
                                elif event_type == 'status':
                                    status = params.get('status', {})
                                    state = status.get('state', 'unknown')
                                    is_final = params.get('final', False)
                                    
                                    print(f"📊 Status: {state} (final: {is_final})")
                                    
                                    if is_final and 'completed' in state.lower():
                                        print(f"🏁 Task completed with {artifact_count} artifacts received")
                                        break
                            
                        except json.JSONDecodeError as e:
                            print(f"⚠️  Failed to parse SSE data: {e}")
                            print(f"Raw line: {line}")
                    
                    elif line.startswith(': '):
                        # Keep-alive comment, ignore
                        continue
        
        except asyncio.TimeoutError:
            print("⏰ Timeout waiting for events")
        except Exception as e:
            print(f"❌ Error during streaming: {e}")

async def main():
    """Main function."""
    print("🚀 Testing A2A Server Streaming Artifacts")
    print("=" * 50)
    
    await test_streaming_artifacts()
    
    print("\n" + "=" * 50)
    print("🔍 Expected: 10 artifacts + status updates")
    print("🔍 If you see fewer artifacts, there's a streaming issue")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user")
        sys.exit(0)