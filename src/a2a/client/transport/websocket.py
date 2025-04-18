# a2a/client/transport/websocket.py
"""
Async WebSocket transport for JSON-RPC 2.0 using httpx.
Implements JSONRPCTransport protocol for A2A.
"""
from __future__ import annotations
import json
from typing import Any, AsyncIterator, Optional

import httpx
from a2a.json_rpc.models import Json
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.transport import JSONRPCTransport


class JSONRPCWebSocketClient(JSONRPCTransport):
    """
    WebSocket transport for JSON-RPC 2.0 over ws:// or wss:// endpoints.

    Usage:
        client = JSONRPCWebSocketClient("wss://agent.example.com/ws")
        result = await client.call("tasks/get", {"id": task_id})
        async for msg in client.stream():
            handle(msg)
    """
    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self.url = url
        self._client = httpx.AsyncClient(timeout=timeout)
        self._ws: Optional[httpx.WebSocket] = None

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        if self._ws is None or self._ws.is_closed:
            self._ws = await self._client.ws_connect(self.url)

    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and return the `result`."""
        await self.connect()
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params, "id": None}
        await self._ws.send_json(payload)
        msg = await self._ws.receive_json()
        if msg.get("error"):
            err = msg["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        return msg.get("result")

    async def notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        await self.connect()
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._ws.send_json(payload)

    async def stream(self) -> AsyncIterator[Json]:
        """Stream incoming JSON-RPC messages over WebSocket."""
        await self.connect()
        assert self._ws is not None
        while True:
            msg = await self._ws.receive_json()
            yield msg

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None and not self._ws.is_closed:
            await self._ws.aclose()
        await self._client.aclose()
