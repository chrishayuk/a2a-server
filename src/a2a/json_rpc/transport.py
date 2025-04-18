# a2a/json_rpc/transport.py
"""
Abstract transport interface for A2A JSON-RPC.
Defines the protocol for sending requests, notifications, and receiving streams.
"""

from __future__ import annotations
from typing import Any, AsyncIterator, Protocol

from a2a.json_rpc.models import Json


class JSONRPCTransport(Protocol):
    """Protocol for JSON-RPC transport implementations."""

    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and return the parsed `result` field."""
        ...

    async def notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        ...

    def stream(self) -> AsyncIterator[Json]:
        """Receive a stream of JSON-RPC messages (for subscriptions)."""
        ...
