from __future__ import annotations

"""
Async HTTP transport for JSON-RPC 2.0 using httpx.
Implements JSONRPCTransport protocol for A2A.
"""
import json
import sys
from typing import Any, AsyncIterator
from uuid import uuid4

import httpx
from pydantic.json import pydantic_encoder

from a2a.json_rpc.models import Json
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.transport import JSONRPCTransport


class JSONRPCHTTPClient(JSONRPCTransport):
    """
    HTTP transport for JSON-RPC 2.0 over REST endpoints.

    Usage:
        client = JSONRPCHTTPClient("https://api.agent.com/jsonrpc")
        result = await client.call("tasks/get", {"id": task_id})
    """
    def __init__(self, endpoint: str, timeout: float = 10.0) -> None:
        self.endpoint = endpoint
        self._client = httpx.AsyncClient(timeout=timeout)

    async def _check_server_reachable(self) -> None:
        """Check if the server is reachable before making calls."""
        server_url = self.endpoint.rsplit("/", 1)[0]  # Remove "/rpc" to get base URL
        try:
            await self._client.get(server_url, timeout=3.0)
        except httpx.ConnectError:
            print(f"Error: Cannot connect to A2A server at {server_url}")
            print("Please ensure the server is running with: a2a-server --host 0.0.0.0 --port 8000")
            sys.exit(1)
        except Exception as e:
            print(f"Warning: Could not verify server availability: {e}")

    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and return the `result`."""
        # Generate a real ID so the server returns a response rather than treating it as a notification
        request_id = str(uuid4())

        # Build envelope
        envelope: Json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }

        # Serialize all Pydantic objects and enums properly
        serialized = json.loads(json.dumps(envelope, default=pydantic_encoder))

        # Check server before first call
        try:
            # Send
            response = await self._client.post(self.endpoint, json=serialized)
            response.raise_for_status()
        except httpx.ConnectError:
            # If connection fails, check if server is running and provide helpful message
            await self._check_server_reachable()
            # If _check_server_reachable didn't exit, retry the original request
            response = await self._client.post(self.endpoint, json=serialized)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                print(f"Error: RPC endpoint {self.endpoint} not found")
                print("Please ensure the A2A server is running and the endpoint is correct")
                sys.exit(1)
            raise

        data = response.json()
        if data.get("error"):
            err = data["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        return data.get("result")

    async def notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        envelope: Json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        serialized = json.loads(json.dumps(envelope, default=pydantic_encoder))
        try:
            response = await self._client.post(self.endpoint, json=serialized)
            response.raise_for_status()
        except httpx.ConnectError:
            await self._check_server_reachable()
            # If _check_server_reachable didn't exit, retry the original request
            response = await self._client.post(self.endpoint, json=serialized)
            response.raise_for_status()

    def stream(self) -> AsyncIterator[Json]:
        """HTTP transport does not support streaming subscriptions."""
        raise NotImplementedError("HTTP transport does not support streaming")