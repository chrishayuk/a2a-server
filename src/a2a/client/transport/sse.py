# File: a2a/client/transport/sse.py
from __future__ import annotations
"""
JSON‑RPC over HTTP + Server‑Sent‑Events transport.

•  POST tasks/sendSubscribe → merged SSE response (no initial JSON‑RPC result)
•  GET  /events             → pure SSE stream
"""

import json
import logging
import uuid
from typing import Any, AsyncIterator, Optional

import httpx

from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.models import Json
from a2a.json_rpc.transport import JSONRPCTransport

logger = logging.getLogger("a2a-client.sse")


class JSONRPCSSEClient(JSONRPCTransport):
    def __init__(
        self,
        endpoint: str,
        sse_endpoint: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        # RPC endpoint, e.g. http://host/handler/rpc
        self.endpoint = endpoint.rstrip("/")
        # Alias for sendSubscribe (must hit /handler, not /handler/rpc)
        if self.endpoint.endswith("/rpc"):
            self.alias_endpoint = self.endpoint.rsplit("/rpc", 1)[0]
        else:
            self.alias_endpoint = self.endpoint
        # SSE GET endpoint for standalone streams
        self.sse_endpoint = sse_endpoint or (self.alias_endpoint + "/events")

        self._client = httpx.AsyncClient(timeout=timeout)
        self._pending_resp: Optional[httpx.Response] = None
        self._pending_iter: Optional[AsyncIterator[str]] = None
        self._shutdown = False

    async def call(self, method: str, params: Any) -> Any:
        envelope: Json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": str(uuid.uuid4()),
        }

        # For sendSubscribe → POST to alias to get merged SSE
        url = self.alias_endpoint if method == "tasks/sendSubscribe" else self.endpoint
        req = self._client.build_request("POST", url, json=envelope)
        resp = await self._client.send(req, stream=True)
        resp.raise_for_status()

        ctype = resp.headers.get("content-type", "")

        if ctype.startswith("text/event-stream"):
            # Don’t consume any lines here—stash them for .stream()
            self._pending_resp = resp
            self._pending_iter = resp.aiter_lines()
            # Return None so A2AClient.send_subscribe can ignore it
            return None

        # Otherwise, classic JSON‑RPC reply
        data = await resp.json()
        if data.get("error"):
            err = data["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        return data.get("result")

    async def notify(self, method: str, params: Any) -> None:
        envelope: Json = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._client.post(self.endpoint, json=envelope)

    async def _iter_pending(self) -> AsyncIterator[Json]:
        """Yield parsed JSON objects from the merged SSE stream."""
        if self._pending_iter is None or self._pending_resp is None:
            raise RuntimeError("stream() called without a pending merged SSE")

        async for line in self._pending_iter:
            if not line.startswith("data:"):
                continue
            try:
                yield json.loads(line[5:].strip())
            except json.JSONDecodeError:
                yield {"raw": line}

        await self._pending_resp.aclose()
        self._pending_resp = None
        self._pending_iter = None

    def stream(self) -> AsyncIterator[Json]:
        """
        Return an async iterator over SSE messages:

        • If `.call("tasks/sendSubscribe")` already opened a merged stream,
          we drain _that_ (`_iter_pending`).
        • Otherwise → open a standalone GET /events SSE stream.
        """
        if self._pending_iter is not None:
            return self._iter_pending()

        async def _aiter():
            headers = {"accept": "text/event-stream"}
            async with self._client.stream("GET", self.sse_endpoint, headers=headers) as resp:
                resp.raise_for_status()
                logger.debug("connected to SSE %s", self.sse_endpoint)

                try:
                    async for line in resp.aiter_lines():
                        if self._shutdown:
                            break
                        if not line.startswith("data:"):
                            continue
                        try:
                            yield json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            yield {"raw": line}
                finally:
                    logger.debug("SSE connection closed")

        return _aiter()

    async def close(self) -> None:
        self._shutdown = True
        if self._pending_resp is not None:
            await self._pending_resp.aclose()
            self._pending_resp = None
            self._pending_iter = None
        await self._client.aclose()
