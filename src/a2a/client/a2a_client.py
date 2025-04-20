# File: a2a/client/a2a_client.py
from __future__ import annotations
"""
High‑level A2A client: wraps any JSON‑RPC transport and provides domain‑specific
methods.
"""

import logging
from typing import Any, AsyncIterator, Type, Union, Dict

from a2a.json_rpc.transport import JSONRPCTransport
from a2a.client.transport.http import JSONRPCHTTPClient
from a2a.client.transport.websocket import JSONRPCWebSocketClient
from a2a.client.transport.sse import JSONRPCSSEClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.spec import (
    Task,
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
    TaskPushNotificationConfig,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)

logger = logging.getLogger("a2a-client")


class A2AClient:
    """
    Agent‑to‑Agent high‑level client.

    Accepts any JSONRPCTransport, remains transport‑agnostic,
    and uses Pydantic spec models for all inputs/outputs.
    """

    # ------------------------------------------------------------------ #
    #  construction helpers                                              #
    # ------------------------------------------------------------------ #
    def __init__(self, transport: JSONRPCTransport) -> None:
        self.transport = transport

    @classmethod
    def over_http(cls: Type["A2AClient"], endpoint: str, timeout: float = 10.0) -> "A2AClient":
        return cls(JSONRPCHTTPClient(endpoint, timeout=timeout))

    @classmethod
    def over_ws(cls: Type["A2AClient"], url: str, timeout: float = 10.0) -> "A2AClient":
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
    #  basic RPC wrappers                                                #
    # ------------------------------------------------------------------ #
    async def send_task(self, params: TaskSendParams) -> Task:
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/send", payload)
        return Task.model_validate(raw)

    async def get_task(self, params: TaskQueryParams) -> Task:
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/get", payload)
        return Task.model_validate(raw)

    async def cancel_task(self, params: TaskIdParams) -> None:
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        await self.transport.call("tasks/cancel", payload)

    async def set_push_notification(
        self, params: TaskPushNotificationConfig
    ) -> TaskPushNotificationConfig:
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/pushNotification/set", payload)
        return TaskPushNotificationConfig.model_validate(raw)

    async def get_push_notification(
        self, params: TaskIdParams
    ) -> TaskPushNotificationConfig:
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/pushNotification/get", payload)
        return TaskPushNotificationConfig.model_validate(raw)

    # ------------------------------------------------------------------ #
    #  streaming helpers                                                 #
    # ------------------------------------------------------------------ #
    async def send_subscribe(
        self,
        params: TaskSendParams,
    ) -> AsyncIterator[Union[Dict, TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        """
        Send a task **and** subscribe to its status/artifact events in one call.

        The correct order is: perform the JSON‑RPC call first (which opens a
        merged SSE response inside the transport) **then** obtain the iterator.
        """
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        task_result = await self.transport.call("tasks/sendSubscribe", payload)

        # grab iterator after the call – now the transport has a pending stream
        iterator = self.transport.stream()

        task_id = task_result.get("id") if isinstance(task_result, dict) else None
        if task_id:
            logger.debug("Subscribing to task ID: %s", task_id)

        async for msg in iterator:
            try:
                logger.debug("Received event message: %s", msg)

                # normal “tasks/event” notifications
                if isinstance(msg, dict) and msg.get("method") == "tasks/event":
                    yield msg.get("params", {})
                # bare event objects
                elif isinstance(msg, dict) and (
                    "status" in msg or "artifact" in msg or "final" in msg
                ):
                    yield msg
                # wrapped inside {"result": …}
                elif isinstance(msg, dict) and "result" in msg:
                    yield msg["result"]
                else:
                    logger.warning("Unrecognized message format: %s", msg)
                    yield msg
            except Exception as exc:
                logger.error("Failed to process event: %s", exc, exc_info=True)
                yield msg

    async def resubscribe(
        self,
        params: TaskQueryParams,
    ) -> AsyncIterator[Union[Dict, TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        """
        Re‑attach to a running task and stream remaining events.

        Same ordering fix as in `send_subscribe()`.
        """
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        await self.transport.call("tasks/resubscribe", payload)

        logger.debug("Resubscribed to task ID: %s", params.id)

        iterator = self.transport.stream()

        async for msg in iterator:
            try:
                logger.debug("Received event message: %s", msg)

                if isinstance(msg, dict) and msg.get("method") == "tasks/event":
                    yield msg.get("params", {})
                elif isinstance(msg, dict) and (
                    "status" in msg or "artifact" in msg or "final" in msg
                ):
                    yield msg
                elif isinstance(msg, dict) and "result" in msg:
                    yield msg["result"]
                else:
                    logger.warning("Unrecognized message format: %s", msg)
                    yield msg
            except Exception as exc:
                logger.error("Failed to process event: %s", exc, exc_info=True)
                yield msg