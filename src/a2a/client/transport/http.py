# File: a2a/client/transport/http.py
from __future__ import annotations
"""
Async HTTP transport for JSON‑RPC 2.0 using httpx.
• Understands normal JSON replies **and** “merged” Server‑Sent‑Events
  replies (Content‑Type: text/event‑stream).
"""
import json
import sys
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

import httpx
from pydantic.json import pydantic_encoder

from a2a.json_rpc.models import Json
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.transport import JSONRPCTransport


class JSONRPCHTTPClient(JSONRPCTransport):
    """
    HTTP transport for JSON‑RPC 2.0.

    • If the server responds with *application/json* → behaves exactly as
      before.
    • If the server responds with *text/event‑stream* → the first chunk
      is treated as the JSON‑RPC response, the remaining chunks are
      exposed via ``stream()``.
    """

    def __init__(self, endpoint: str, timeout: float = 10.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        self._pending_sse: Optional[httpx.Response] = None   # <- new

    # ------------------------------------------------------------------ #
    #  Public JSON‑RPC  ------------------------------------------------- #
    # ------------------------------------------------------------------ #
    async def call(self, method: str, params: Any) -> Any:
        request_id = str(uuid4())
        envelope: Json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }

        payload = json.loads(json.dumps(envelope, default=pydantic_encoder))

        resp = await self._client.post(self.endpoint, json=payload)
        resp.raise_for_status()

        ctype = resp.headers.get("content-type", "")

        # ── Normal JSON response ───────────────────────────────────────
        if ctype.startswith("application/json"):
            data = resp.json()
            if data.get("error"):
                err = data["error"]
                raise JSONRPCError(message=err.get("message"), data=err.get("data"))
            return data.get("result")

        # ── Merged SSE stream ──────────────────────────────────────────
        if ctype.startswith("text/event-stream"):
            # Save response object so .stream() can iterate over it later
            self._pending_sse = resp

            # First line is “data: {...}\n”
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    first = json.loads(line.removeprefix("data:").strip())
                    break
            else:  # pragma: no cover – should never happen
                raise JSONRPCError(message="Empty SSE stream")

            if first.get("error"):
                err = first["error"]
                raise JSONRPCError(message=err.get("message"), data=err.get("data"))
            return first.get("result")

        # ── Unknown reply type ─────────────────────────────────────────
        raise JSONRPCError(message=f"Unsupported Content‑Type: {ctype}")

    async def notify(self, method: str, params: Any) -> None:
        envelope: Json = {"jsonrpc": "2.0", "method": method, "params": params}
        payload = json.loads(json.dumps(envelope, default=pydantic_encoder))
        await self._client.post(self.endpoint, json=payload)

    # ------------------------------------------------------------------ #
    #  Streaming interface  -------------------------------------------- #
    # ------------------------------------------------------------------ #
    async def _sse_iterator(self) -> AsyncIterator[Json]:
        """
        Yields the remaining lines of the saved SSE response (after the
        first “data:” line already consumed in ``call``).
        """
        if self._pending_sse is None:
            raise RuntimeError("stream() called before a merged SSE call")

        async for line in self._pending_sse.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                yield json.loads(line.removeprefix("data:").strip())
            except json.JSONDecodeError:
                yield {"raw": line}  # pass through un‑parseable chunks

        await self._pending_sse.aclose()
        self._pending_sse = None  # reset once stream ends

    def stream(self) -> AsyncIterator[Json]:
        """
        Return an async iterator for the merged SSE stream.

        Only valid immediately *after* a call() that produced an SSE
        response (i.e. tasks/sendSubscribe).  Otherwise raises
        NotImplementedError to preserve prior semantics.
        """
        if self._pending_sse is None:
            raise NotImplementedError("HTTP transport supports streaming only for merged‑SSE responses")
        return self._sse_iterator()
