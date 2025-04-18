# a2a/client/transport/stdio.py
"""
Stdio transport for JSON-RPC 2.0 over standard input/output.
Implements JSONRPCTransport for A2A, enabling CLI-based agents.
"""
from __future__ import annotations
import sys
import json
import asyncio
from typing import Any, AsyncIterator, Optional

from a2a.json_rpc.models import Json
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.transport import JSONRPCTransport


def _read_line() -> str:
    """Blocking read of a line from stdin."""
    return sys.stdin.readline()


class JSONRPCStdioTransport(JSONRPCTransport):
    """
    Stdio transport for JSON-RPC: sends requests via stdout and reads responses from stdin.

    Suitable for CLI tools or subprocess-based agents.
    """
    def __init__(self) -> None:
        # nothing to initialize on stdout/stdin
        pass

    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and await a response."""
        # Construct JSON-RPC envelope with null ID (server should assign one)
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params, "id": None}
        # Write to stdout
        print(json.dumps(payload), flush=True)
        # Read response line asynchronously
        loop = asyncio.get_event_loop()
        line = await loop.run_in_executor(None, _read_line)
        if not line:
            raise ConnectionError("End of input")
        data = json.loads(line)
        if data.get("error"):
            err = data["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        return data.get("result")

    async def notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        payload: Json = {"jsonrpc": "2.0", "method": method, "params": params}
        print(json.dumps(payload), flush=True)

    async def stream(self) -> AsyncIterator[Json]:
        """Continuously read JSON-RPC messages from stdin."""
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, _read_line)
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                yield msg
            except json.JSONDecodeError:
                continue
