#!/usr/bin/env python3
"""
SSE MCP Diagnostic Script
========================

Comprehensive diagnostic tool to debug SSE MCP connection issues.
This script will test both the working mock server and the real server
to identify protocol differences.
"""

import asyncio
import aiohttp
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    
    # Look for .env file in current directory and parent directories
    env_file = None
    current_dir = Path.cwd()
    
    # Check current directory and up to 3 parent directories
    for i in range(4):
        check_path = current_dir / '.env'
        if check_path.exists():
            env_file = check_path
            break
        current_dir = current_dir.parent
    
    if env_file:
        load_dotenv(env_file)
        print(f"✅ Loaded environment from: {env_file}")
    else:
        print("⚠️  No .env file found")
        
except ImportError:
    print("ℹ️  dotenv not available, using system environment variables only")
except Exception as e:
    print(f"⚠️  Could not load .env: {e}")

# Test configurations
MOCK_SERVER = "http://localhost:8020"
REAL_SERVER = "https://application-cd.1vqsrjfxmls7.eu-gb.codeengine.appdomain.cloud"

class SSEMCPDiagnostic:
    """Diagnostic tool for SSE MCP connections."""
    
    def __init__(self):
        self.session = None
        self.bearer_token = os.getenv('MCP_BEARER_TOKEN')
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def log(self, level: str, message: str, **kwargs):
        """Enhanced logging with context."""
        timestamp = time.strftime("%H:%M:%S")
        prefix = {
            'INFO': '🔍',
            'SUCCESS': '✅', 
            'WARNING': '⚠️',
            'ERROR': '❌',
            'DEBUG': '🐛'
        }.get(level, '📋')
        
        print(f"{prefix} [{timestamp}] {message}")
        if kwargs:
            for key, value in kwargs.items():
                print(f"    {key}: {value}")
    
    async def test_basic_connection(self, server_url: str) -> bool:
        """Test basic HTTP connection to server."""
        self.log('INFO', f"Testing basic connection to {server_url}")
        
        try:
            async with self.session.get(f"{server_url}/") as resp:
                self.log('SUCCESS', f"Basic connection OK: {resp.status}")
                return True
        except Exception as e:
            self.log('ERROR', f"Basic connection failed: {e}")
            return False
    
    async def test_sse_endpoint(self, server_url: str) -> Optional[Dict[str, Any]]:
        """Test SSE endpoint connection and initial handshake."""
        self.log('INFO', f"Testing SSE endpoint: {server_url}/sse")
        
        # Determine if this server needs authentication
        is_real_server = 'application-cd.1vqsrjfxmls7.eu-gb.codeengine.appdomain.cloud' in server_url
        
        headers = {}
        if is_real_server and self.bearer_token:
            headers['Authorization'] = f'Bearer {self.bearer_token}'
            self.log('DEBUG', "Using bearer token authentication for real server")
        elif is_real_server:
            self.log('WARNING', "Real server detected but no bearer token available")
        else:
            self.log('DEBUG', "Mock server - no authentication needed")
        
        try:
            sse_url = f"{server_url}/sse"
            async with self.session.get(sse_url, headers=headers) as resp:
                self.log('INFO', f"SSE endpoint response: {resp.status}")
                
                if resp.status != 200:
                    self.log('ERROR', f"SSE endpoint failed: {resp.status}")
                    body = await resp.text()
                    self.log('DEBUG', f"Response body: {body}")
                    return None
                
                # Read first few SSE events with timeout
                events = []
                endpoint_info = {}
                current_event = None
                
                try:
                    # Set a timeout for reading events
                    async with asyncio.timeout(10.0):  # Increased timeout
                        async for line in resp.content:
                            line_str = line.decode('utf-8').strip()
                            if not line_str:
                                continue
                                
                            events.append(line_str)
                            self.log('DEBUG', f"SSE event: {line_str}")
                            
                            # Handle A2A-style SSE format
                            if line_str.startswith('data: '):
                                data_content = line_str[6:].strip()
                                
                                # Try to parse as JSON (A2A format)
                                try:
                                    data = json.loads(data_content)
                                    if 'endpoint' in data:
                                        endpoint_info.update(data)
                                        self.log('SUCCESS', f"Got JSON endpoint info: {data}")
                                        break
                                    elif 'method' in data:
                                        # This might be an A2A-style event
                                        self.log('DEBUG', f"Got A2A event: {data.get('method')}")
                                except json.JSONDecodeError:
                                    # Raw endpoint path (mock server format)
                                    if data_content.startswith('/'):
                                        endpoint_info['endpoint'] = data_content
                                        self.log('SUCCESS', f"Got endpoint path: {data_content}")
                                        break
                                    else:
                                        self.log('DEBUG', f"Raw SSE data: {data_content}")
                                        
                            elif line_str.startswith('event: '):
                                current_event = line_str[7:].strip()
                                self.log('DEBUG', f"SSE event type: {current_event}")
                                
                                # If this is an endpoint event, the next data line will have the path
                                if current_event == 'endpoint':
                                    continue
                                    
                            elif line_str.startswith(': '):
                                # Keep-alive comment, ignore
                                continue
                            
                            # Stop after reasonable number of events
                            if len(events) >= 20:
                                self.log('WARNING', "Reached event limit, stopping")
                                break
                                
                except asyncio.TimeoutError:
                    self.log('WARNING', "Timeout reading SSE events")
                
                self.log('SUCCESS', "SSE connection established")
                return endpoint_info or {"status": "connected"}
                
        except Exception as e:
            self.log('ERROR', f"SSE endpoint test failed: {e}")
            return None
    
    async def test_mcp_protocol(self, server_url: str, endpoint_info: Dict[str, Any]) -> bool:
        """Test MCP protocol communication."""
        self.log('INFO', "Testing MCP protocol communication")
        
        if not endpoint_info:
            self.log('ERROR', "No endpoint info available for MCP testing")
            return False
        
        is_real_server = 'application-cd.1vqsrjfxmls7.eu-gb.codeengine.appdomain.cloud' in server_url
        
        # Extract message URL from endpoint info
        message_url = None
        if 'endpoint' in endpoint_info:
            message_url = f"{server_url}{endpoint_info['endpoint']}"
        elif 'session_id' in endpoint_info:
            # Try common patterns
            patterns = [
                f"/messages/?session_id={endpoint_info['session_id']}",
                f"/mcp?session_id={endpoint_info['session_id']}"
            ]
            for pattern in patterns:
                test_url = f"{server_url}{pattern}"
                if await self.test_message_endpoint(test_url, is_real_server):
                    message_url = test_url
                    break
        
        if not message_url:
            self.log('ERROR', "Could not determine message endpoint")
            return False
            
        self.log('INFO', f"Using message endpoint: {message_url}")
        
        # Test sequence: ping -> tools/list -> tools/call
        tests = [
            ('ping', {}),
            ('tools/list', {}),
        ]
        
        for method, params in tests:
            success = await self.send_mcp_message(message_url, method, params, is_real_server)
            if not success and method == 'tools/list':
                # Try alternative formats for tools/list
                alt_formats = [
                    ('tools/list', {'include_hidden': False}),
                    ('tools/list', {'detailed': True}),
                    ('list_tools', {}),
                    ('tools.list', {}),
                ]
                
                for alt_method, alt_params in alt_formats:
                    self.log('INFO', f"Trying alternative format: {alt_method}")
                    success = await self.send_mcp_message(message_url, alt_method, alt_params, is_real_server)
                    if success:
                        break
            
            if not success:
                self.log('ERROR', f"MCP method {method} failed")
                return False
        
        return True
    
    async def test_message_endpoint(self, message_url: str, is_real_server: bool = False) -> bool:
        """Test if a message endpoint responds to ping."""
        try:
            headers = {'Content-Type': 'application/json'}
            if is_real_server and self.bearer_token:
                headers['Authorization'] = f'Bearer {self.bearer_token}'
            
            ping_message = {
                "jsonrpc": "2.0",
                "id": "test-ping",
                "method": "ping",
                "params": {}
            }
            
            async with self.session.post(message_url, json=ping_message, headers=headers) as resp:
                return resp.status == 200
        except:
            return False
    
    async def send_mcp_message(self, message_url: str, method: str, params: Dict[str, Any], is_real_server: bool = False) -> bool:
        """Send an MCP message and analyze the response."""
        self.log('DEBUG', f"Sending MCP message: {method}")
        
        headers = {'Content-Type': 'application/json'}
        if is_real_server and self.bearer_token:
            headers['Authorization'] = f'Bearer {self.bearer_token}'
        
        # Extract session_id from URL if present
        session_id = None
        if 'session_id=' in message_url:
            session_id = message_url.split('session_id=')[1].split('&')[0]
            self.log('DEBUG', f"Extracted session_id: {session_id}")
        
        # Build message with session_id if available
        final_params = {}
        if session_id:
            final_params["session_id"] = session_id
        
        # Merge with any additional params
        if params:
            final_params.update(params)
            
        message = {
            "jsonrpc": "2.0",
            "id": f"test-{int(time.time())}",
            "method": method,
            "params": final_params
        }
        
        self.log('DEBUG', f"Request payload: {json.dumps(message, indent=2)}")
        
        try:
            async with self.session.post(message_url, json=message, headers=headers) as resp:
                self.log('DEBUG', f"Response status: {resp.status}")
                
                if resp.status != 200:
                    body = await resp.text()
                    self.log('ERROR', f"HTTP error {resp.status}: {body}")
                    return False
                
                try:
                    response = await resp.json()
                    self.log('DEBUG', f"Response: {json.dumps(response, indent=2)}")
                    
                    if 'error' in response and response['error']:
                        error = response['error']
                        self.log('ERROR', f"JSON-RPC error: {error}")
                        
                        # Specific analysis for -32602 (Invalid params)
                        if isinstance(error, dict) and error.get('code') == -32602:
                            self.log('WARNING', "Invalid parameters error - analyzing...")
                            self.analyze_parameter_error(method, message["params"], error)
                        
                        return False
                    else:
                        self.log('SUCCESS', f"Method {method} succeeded")
                        if 'result' in response:
                            result = response['result']
                            if method == 'tools/list' and isinstance(result, dict) and 'tools' in result:
                                tools = result['tools']
                                self.log('SUCCESS', f"Found {len(tools)} tools")
                                for tool in tools[:3]:  # Show first 3
                                    tool_name = tool.get('name', 'unknown') if isinstance(tool, dict) else str(tool)
                                    self.log('INFO', f"Tool: {tool_name}")
                            elif method == 'ping':
                                self.log('SUCCESS', "Ping successful")
                        return True
                        
                except json.JSONDecodeError as e:
                    body = await resp.text()
                    self.log('ERROR', f"Invalid JSON response: {e}")
                    self.log('DEBUG', f"Raw response: {body}")
                    return False
                    
        except Exception as e:
            self.log('ERROR', f"Request failed: {e}")
            return False
    
    def analyze_parameter_error(self, method: str, params: Dict[str, Any], error: Dict[str, Any]):
        """Analyze parameter validation errors."""
        self.log('INFO', "Analyzing parameter error...")
        
        error_msg = error.get('message', '')
        
        if method == 'tools/list':
            self.log('INFO', "tools/list parameter suggestions:")
            self.log('INFO', "  - Try empty params: {}")
            self.log('INFO', "  - Try with cursor: {'cursor': null}")
            self.log('INFO', "  - Try different method name: 'list_tools'")
            
        if 'required' in error_msg.lower():
            self.log('WARNING', "Server expects required parameters")
        if 'unknown' in error_msg.lower():
            self.log('WARNING', "Server doesn't recognize parameter names")
    
    async def compare_servers(self):
        """Compare mock vs real server behavior."""
        self.log('INFO', "=" * 60)
        self.log('INFO', "COMPARING MOCK VS REAL SERVER")
        self.log('INFO', "=" * 60)
        
        servers = [
            ("MOCK SERVER", MOCK_SERVER),
            ("REAL SERVER", REAL_SERVER)
        ]
        
        for name, url in servers:
            self.log('INFO', f"\n🔍 Testing {name}: {url}")
            self.log('INFO', "-" * 40)
            
            # Basic connection
            if not await self.test_basic_connection(url):
                self.log('ERROR', f"{name} basic connection failed")
                continue
            
            # SSE endpoint
            endpoint_info = await self.test_sse_endpoint(url)
            if not endpoint_info:
                self.log('ERROR', f"{name} SSE connection failed")
                continue
            
            # MCP protocol
            await self.test_mcp_protocol(url, endpoint_info)
    
    async def run_diagnostics(self):
        """Run complete diagnostic suite."""
        self.log('INFO', "🚀 Starting SSE MCP Diagnostics")
        self.log('INFO', "=" * 60)
        
        # Environment check
        self.log('INFO', "Environment Configuration:")
        self.log('INFO', f"MCP_BEARER_TOKEN: {'SET' if self.bearer_token else 'NOT SET'}")
        self.log('INFO', f"MCP_SERVER_URL_MAP: {os.getenv('MCP_SERVER_URL_MAP', 'NOT SET')}")
        self.log('INFO', f"MCP_SERVER_NAME_MAP: {os.getenv('MCP_SERVER_NAME_MAP', 'NOT SET')}")
        
        # Server comparison
        await self.compare_servers()
        
        self.log('INFO', "\n" + "=" * 60)
        self.log('INFO', "🎯 DIAGNOSTIC COMPLETE")
        self.log('INFO', "=" * 60)


async def main():
    """Main diagnostic function."""
    try:
        async with SSEMCPDiagnostic() as diagnostic:
            await diagnostic.run_diagnostics()
    except KeyboardInterrupt:
        print("\n⏹️  Diagnostics interrupted by user")
    except Exception as e:
        print(f"❌ Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())