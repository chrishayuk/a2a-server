#!/usr/bin/env python3
# a2a/client/a2a_client.py
"""
High‑level A2A client: wraps any JSON‑RPC transport and provides domain‑specific
methods.

Key changes
-----------
* Unified helper ``_coerce_stream_event`` converts raw SSE payloads into
  ``TaskStatusUpdateEvent`` / ``TaskArtifactUpdateEvent`` instances **while
  discarding the helper key ``type``** that the transport adds for the
  consumer‑side router.  This prevents Pydantic validation errors and means
  the caller always receives real spec objects.
* Streaming loops for ``send_subscribe`` and ``resubscribe`` now use the
  helper and are identical apart from the initial RPC call.
* No external behaviour changes – just correct artifact handling.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, Type, Union

from a2a.client.transport.http import JSONRPCHTTPClient
from a2a.client.transport.sse import JSONRPCSSEClient
from a2a.client.transport.websocket import JSONRPCWebSocketClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.spec import (
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskPushNotificationConfig,
    TaskQueryParams,
    TaskSendParams,
    TaskStatusUpdateEvent,
)
from a2a.json_rpc.transport import JSONRPCTransport

logger = logging.getLogger("a2a-client")


class A2AClient:
    """Agent‑to‑Agent high‑level client (transport‑agnostic)."""

    # ------------------------------------------------------------------ #
    # construction helpers                                               #
    # ------------------------------------------------------------------ #
    def __init__(self, transport: JSONRPCTransport) -> None:
        self.transport = transport

    @classmethod
    def over_http(
        cls: Type["A2AClient"], endpoint: str, timeout: float = 10.0
    ) -> "A2AClient":
        return cls(JSONRPCHTTPClient(endpoint, timeout=timeout))

    @classmethod
    def over_ws(
        cls: Type["A2AClient"], url: str, timeout: float = 10.0
    ) -> "A2AClient":
        return cls(JSONRPCWebSocketClient(url, timeout=timeout))

    @classmethod
    def over_sse(
        cls: Type["A2AClient"],
        endpoint: str,
        sse_endpoint: str | None = None,
        timeout: float = 10.0,
    ) -> "A2AClient":
        return cls(JSONRPCSSEClient(endpoint, sse_endpoint=sse_endpoint, timeout=timeout))

    # ------------------------------------------------------------------ #
    # basic RPC wrappers                                                 #
    # ------------------------------------------------------------------ #
    async def send_task(self, params: TaskSendParams) -> Task:
        raw = await self.transport.call(
            "tasks/send", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )
        return Task.model_validate(raw)

    async def get_task(self, params: TaskQueryParams) -> Task:
        raw = await self.transport.call(
            "tasks/get", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )
        return Task.model_validate(raw)

    async def cancel_task(self, params: TaskIdParams) -> None:
        await self.transport.call(
            "tasks/cancel", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )

    async def set_push_notification(
        self, params: TaskPushNotificationConfig
    ) -> TaskPushNotificationConfig:
        raw = await self.transport.call(
            "tasks/pushNotification/set",
            params.model_dump(mode="json", exclude_none=True, by_alias=True),
        )
        return TaskPushNotificationConfig.model_validate(raw)

    async def get_push_notification(
        self, params: TaskIdParams
    ) -> TaskPushNotificationConfig:
        raw = await self.transport.call(
            "tasks/pushNotification/get",
            params.model_dump(mode="json", exclude_none=True, by_alias=True),
        )
        return TaskPushNotificationConfig.model_validate(raw)

    # ------------------------------------------------------------------ #
    # helpers                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coerce_stream_event(evt: Dict[str, Any]) -> Union[
        TaskStatusUpdateEvent, TaskArtifactUpdateEvent, Dict[str, Any]
    ]:
        """Convert raw notification dict to the appropriate spec model.

        The server adds a helper field ``type`` (``status`` | ``artifact``)
        which is *not* part of either spec model, so we drop it before
        validating.
        """
        if "method" in evt and evt.get("method") == "tasks/event":
            evt = evt["params"]

        # At this point evt should be the dictionary produced in transport.http
        if "status" in evt:
            payload = {k: v for k, v in evt.items() if k != "type"}
            return TaskStatusUpdateEvent.model_validate(payload)
        if "artifact" in evt:
            payload = {k: v for k, v in evt.items() if k != "type"}
            return TaskArtifactUpdateEvent.model_validate(payload)
        return evt  # unknown – let the caller decide

    # ------------------------------------------------------------------ #
    # streaming helpers                                                  #
    # ------------------------------------------------------------------ #
    async def send_subscribe(
        self, params: TaskSendParams
    ) -> AsyncIterator[Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        # Initiate the merged SSE connection (first line is the RPC result)
        await self.transport.call(
            "tasks/sendSubscribe", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )

        async for raw_msg in self.transport.stream():
            try:
                yield self._coerce_stream_event(raw_msg)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error parsing stream event: %s", exc, exc_info=True)
                # decide whether to swallow or re‑raise – swallow keeps the stream alive

    async def resubscribe(
        self, params: TaskQueryParams
    ) -> AsyncIterator[Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        await self.transport.call(
            "tasks/resubscribe", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )
        async for raw_msg in self.transport.stream():
            try:
                yield self._coerce_stream_event(raw_msg)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error parsing resubscribe event: %s", exc, exc_info=True)
