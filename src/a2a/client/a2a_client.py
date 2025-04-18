# a2a/client/a2a_client.py
"""
High-level A2A client: wraps any JSON-RPC transport and provides domain-specific methods.
"""

from __future__ import annotations
from typing import Any, AsyncIterator, Type, Union

# a2a transports
from a2a.json_rpc.transport import JSONRPCTransport
from a2a.client.transport.http import JSONRPCHTTPClient
from a2a.client.transport.websocket import JSONRPCWebSocketClient
from a2a.client.transport.sse import JSONRPCSSEClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.models.spec import (
    Task, TaskSendParams, TaskQueryParams, TaskIdParams,
    TaskPushNotificationConfig, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)


class A2AClient:
    """
    Agent2Agent high-level client.

    Accepts any JSONRPCTransport, remains transport-agnostic,
    and uses Pydantic spec models for all inputs/outputs.

    Example:
        client = A2AClient.over_http("https://agent/api")
        params = TaskSendParams(id="123", message=...)
        task = await client.send_task(params)
    """
    def __init__(self, transport: JSONRPCTransport) -> None:
        self.transport = transport

    @classmethod
    def over_http(cls: Type[A2AClient], endpoint: str, timeout: float = 10.0) -> A2AClient:
        """Constructs client over HTTP JSON-RPC transport."""
        return cls(JSONRPCHTTPClient(endpoint, timeout=timeout))

    @classmethod
    def over_ws(cls: Type[A2AClient], url: str, timeout: float = 10.0) -> A2AClient:
        """Constructs client over WebSocket JSON-RPC transport."""
        return cls(JSONRPCWebSocketClient(url, timeout=timeout))

    @classmethod
    def over_sse(
        cls: Type[A2AClient],
        endpoint: str,
        sse_endpoint: str | None = None,
        timeout: float = 10.0,
    ) -> A2AClient:
        """Constructs client over SSE JSON-RPC transport."""
        return cls(JSONRPCSSEClient(endpoint, sse_endpoint=sse_endpoint, timeout=timeout))

    async def send_task(self, params: TaskSendParams) -> Task:
        """Call tasks/send and return the created Task."""
        raw = await self.transport.call("tasks/send", params.model_dump(exclude_none=True))
        return Task.model_validate(raw)

    async def get_task(self, params: TaskQueryParams) -> Task:
        """Call tasks/get and return the requested Task."""
        raw = await self.transport.call("tasks/get", params.model_dump(exclude_none=True))
        return Task.model_validate(raw)

    async def cancel_task(self, params: TaskIdParams) -> None:
        """Call tasks/cancel; resolves when cancellation succeeds."""
        await self.transport.call("tasks/cancel", params.model_dump(exclude_none=True))

    async def set_push_notification(self, params: TaskPushNotificationConfig) -> TaskPushNotificationConfig:
        """Call tasks/pushNotification/set and return the config."""
        raw = await self.transport.call(
            "tasks/pushNotification/set", params.model_dump(exclude_none=True)
        )
        return TaskPushNotificationConfig.model_validate(raw)

    async def get_push_notification(self, params: TaskIdParams) -> TaskPushNotificationConfig:
        """Call tasks/pushNotification/get and return the config."""
        raw = await self.transport.call(
            "tasks/pushNotification/get", params.model_dump(exclude_none=True)
        )
        return TaskPushNotificationConfig.model_validate(raw)

    async def send_subscribe(
        self, params: TaskSendParams,
    ) -> AsyncIterator[Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        """
        Call tasks/sendSubscribe and stream status/artifact events.
        Requires a transport that supports streaming.
        """
        # early check for streaming support
        try:
            iterator = self.transport.stream()
        except NotImplementedError as e:
            raise NotImplementedError("Streaming requires a transport that supports stream()")

        # send the subscribe request
        await self.transport.call("tasks/sendSubscribe", params.model_dump(exclude_none=True))

        # yield incoming events
        async for msg in iterator:
            result = msg.get("result", {})
            if "status" in result:
                yield TaskStatusUpdateEvent.model_validate(result)
            else:
                yield TaskArtifactUpdateEvent.model_validate(result)

    async def resubscribe(
        self, params: TaskQueryParams,
    ) -> AsyncIterator[Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        """
        Call tasks/resubscribe and stream remaining events.
        Requires a transport that supports streaming.
        """
        try:
            iterator = self.transport.stream()
        except NotImplementedError:
            raise NotImplementedError("Streaming requires a transport that supports stream()")

        await self.transport.call("tasks/resubscribe", params.model_dump(exclude_none=True))
        async for msg in iterator:
            result = msg.get("result", {})
            if "status" in result:
                yield TaskStatusUpdateEvent.model_validate(result)
            else:
                yield TaskArtifactUpdateEvent.model_validate(result)