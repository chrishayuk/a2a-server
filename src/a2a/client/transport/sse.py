# File: a2a/client/transport/sse.py
from __future__ import annotations
"""
JSON‑RPC over HTTP + Server‑Sent‑Events transport.

•  POST tasks/sendSubscribe → merged SSE response (first line = JSON‑RPC result)
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
        self.endpoint = endpoint.rstrip("/")
        self.sse_endpoint = (
            sse_endpoint or self.endpoint.rsplit("/", 1)[0].rstrip("/") + "/events"
        )

        self._client = httpx.AsyncClient(timeout=timeout)
        self._pending_resp: Optional[httpx.Response] = None
        self._pending_iter: Optional[AsyncIterator[str]] = None
        self._shutdown = False

    # ------------------------------------------------------------------ #
    # JSON‑RPC call/notify                                               #
    # ------------------------------------------------------------------ #
    async def call(self, method: str, params: Any) -> Any:
        envelope: Json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": str(uuid.uuid4()),
        }

        # open streaming response
        req = self._client.build_request("POST", self.endpoint, json=envelope)
        resp = await self._client.send(req, stream=True)
        resp.raise_for_status()

        ctype = resp.headers.get("content-type", "")

        # ---------- merged SSE stream --------------------------------- #
        if ctype.startswith("text/event-stream"):
            self._pending_resp = resp
            iter_lines = resp.aiter_lines()
            self._pending_iter = iter_lines  # store for later streaming

            # grab first data: line = JSON‑RPC response
            async for line in iter_lines:
                if line.startswith("data:"):
                    first = json.loads(line[5:].strip())
                    break
            else:  # pragma: no cover
                raise JSONRPCError(message="empty SSE stream")

            if first.get("error"):
                err = first["error"]
                raise JSONRPCError(message=err.get("message"), data=err.get("data"))

            return first.get("result", first)

        # ---------- classic JSON reply -------------------------------- #
        data = await resp.json() if resp.content else {}
        if data.get("error"):
            err = data["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        return data.get("result")

    async def notify(self, method: str, params: Any) -> None:
        envelope: Json = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._client.post(self.endpoint, json=envelope)

    # ------------------------------------------------------------------ #
    # streaming helpers                                                  #
    # ------------------------------------------------------------------ #
    async def _iter_pending(self) -> AsyncIterator[Json]:
        """Continue streaming lines from the merged SSE response."""
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
        Return an async iterator:

        • if call() already opened a merged stream → iterate that one
        • otherwise                               → open standalone /events
        """
        if self._pending_iter is not None:           # merged stream
            return self._iter_pending()

        # -------- standalone /events connection ----------------------- #
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

    # ------------------------------------------------------------------ #
    # tidy‑up                                                            #
    # ------------------------------------------------------------------ #
    async def close(self) -> None:
        self._shutdown = True
        if self._pending_resp is not None:
            await self._pending_resp.aclose()
            self._pending_resp = None
            self._pending_iter = None
        await self._client.aclose()
