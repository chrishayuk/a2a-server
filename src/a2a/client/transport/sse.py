# a2a/client/transport/sse.py
"""
SSE transport for JSON-RPC 2.0 using HTTP Server-Sent Events.
Implements JSONRPCTransport for A2A subscriptions.
"""
from __future__ import annotations
import json
from typing import Any, AsyncIterator
import httpx
from a2a.json_rpc.models import Json
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.transport import JSONRPCTransport


class JSONRPCSSEClient(JSONRPCTransport):
    """
    HTTP transport with SSE support for JSON-RPC subscriptions.

    Usage:
        client = JSONRPCSSEClient(endpoint, sse_endpoint)
        result = await client.call("tasks/get", {"id": id})
        async for msg in client.stream():
            handle(msg)
    """
    def __init__(
        self,
        endpoint: str,
        sse_endpoint: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.endpoint = endpoint
        # SSE endpoint (fallback to same endpoint)
        self.sse_endpoint = sse_endpoint or endpoint
        self._client = httpx.AsyncClient(timeout=timeout)
        self._sse_response: httpx.Response | None = None

    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request over HTTP and return the result."""
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params, "id": None}
        response = await self._client.post(self.endpoint, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            err = data["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        return data.get("result")

    async def notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification over HTTP."""
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params}
        response = await self._client.post(self.endpoint, json=payload)
        response.raise_for_status()

    def stream(self) -> AsyncIterator[Json]:
        """Open an SSE connection and yield incoming JSON-RPC messages."""
        # Lazy-open the SSE stream
        self._sse_response = self._client.stream(
            "GET", self.sse_endpoint, headers={"Accept": "text/event-stream"}
        )
        # httpx.stream returns a context manager, but here we iterate manually
        async def _iter_sse():
            async with self._sse_response as resp:
                async for line in resp.aiter_lines():
                    if not line or line.startswith(':'):
                        continue
                    if line.startswith('data:'):
                        payload = line[len('data:'):].strip()
                        try:
                            msg = json.loads(payload)
                            yield msg
                        except json.JSONDecodeError:
                            continue
        return _iter_sse()
