# a2a/client/transport/http.py
"""
Async HTTP transport for JSON-RPC 2.0 using httpx.
Implements JSONRPCTransport protocol for A2A.
"""
from __future__ import annotations
from typing import Any, AsyncIterator

import httpx
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

    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and return the `result`."""
        # Build payload; let server echo or assign ID
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params, "id": None}
        response = await self._client.post(self.endpoint, json=payload)
        response.raise_for_status()
        data = response.json()
        # Handle JSON-RPC error
        if data.get("error"):
            err = data["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        # Return result field
        return data.get("result")

    async def notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params}
        response = await self._client.post(self.endpoint, json=payload)
        response.raise_for_status()

    def stream(self) -> AsyncIterator[Json]:
        """HTTP transport does not support streaming subscriptions."""
        raise NotImplementedError("HTTP transport does not support streaming")
