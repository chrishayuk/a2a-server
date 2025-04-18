# File: a2a/client/a2a_client.py
from __future__ import annotations

"""
High-level A2A client: wraps any JSON-RPC transport and provides domain-specific methods.
"""

import logging
from typing import Any, AsyncIterator, Type, Union, Dict
from uuid import uuid4

# transports
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
    Agent-to-Agent high-level client.

    Accepts any JSONRPCTransport, remains transport-agnostic,
    and uses Pydantic spec models for all inputs/outputs.
    """

    def __init__(self, transport: JSONRPCTransport) -> None:
        self.transport = transport

    @classmethod
    def over_http(
        cls: Type[A2AClient], endpoint: str, timeout: float = 10.0
    ) -> A2AClient:
        """Constructs client over HTTP transport."""
        return cls(JSONRPCHTTPClient(endpoint, timeout=timeout))

    @classmethod
    def over_ws(
        cls: Type[A2AClient], url: str, timeout: float = 10.0
    ) -> A2AClient:
        """Constructs client over WebSocket transport."""
        return cls(JSONRPCWebSocketClient(url, timeout=timeout))

    @classmethod
    def over_sse(
        cls: Type[A2AClient],
        endpoint: str,
        sse_endpoint: str | None = None,
        timeout: float = 10.0,
    ) -> A2AClient:
        """Constructs client over SSE transport."""
        return cls(JSONRPCSSEClient(endpoint, sse_endpoint=sse_endpoint, timeout=timeout))

    async def send_task(self, params: TaskSendParams) -> Task:
        """Call tasks/send and return the created Task."""
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/send", payload)
        return Task.model_validate(raw)

    async def get_task(self, params: TaskQueryParams) -> Task:
        """Call tasks/get and return the requested Task."""
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/get", payload)
        return Task.model_validate(raw)

    async def cancel_task(self, params: TaskIdParams) -> None:
        """Call tasks/cancel; resolves when cancellation succeeds."""
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        await self.transport.call("tasks/cancel", payload)

    async def set_push_notification(
        self, params: TaskPushNotificationConfig
    ) -> TaskPushNotificationConfig:
        """Call tasks/pushNotification/set and return the config."""
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/pushNotification/set", payload)
        return TaskPushNotificationConfig.model_validate(raw)

    async def get_push_notification(
        self, params: TaskIdParams
    ) -> TaskPushNotificationConfig:
        """Call tasks/pushNotification/get and return the config."""
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        raw = await self.transport.call("tasks/pushNotification/get", payload)
        return TaskPushNotificationConfig.model_validate(raw)

    async def send_subscribe(
        self, params: TaskSendParams,
    ) -> AsyncIterator[Union[Dict, TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        """
        Call tasks/sendSubscribe and stream status/artifact events.
        Requires a transport that supports streaming.
        """
        # prepare the SSE iterator
        try:
            iterator = self.transport.stream()
        except NotImplementedError:
            raise NotImplementedError("Streaming requires transport.stream() support")

        # send subscribe RPC
        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        task_result = await self.transport.call("tasks/sendSubscribe", payload)
        
        # Get task ID for correlation
        task_id = None
        if isinstance(task_result, dict) and "id" in task_result:
            task_id = task_result["id"]
            logger.debug(f"Subscribing to task ID: {task_id}")

        # yield events directly as received from the server
        async for msg in iterator:
            try:
                # Debug the incoming message structure
                logger.debug(f"Received event message: {msg}")
                
                # Check if this is a tasks/event notification
                if isinstance(msg, dict) and msg.get("method") == "tasks/event":
                    # Extract params from the notification
                    params = msg.get("params", {})
                    yield params
                # If it's the event data directly
                elif isinstance(msg, dict) and ("status" in msg or "artifact" in msg):
                    yield msg
                # If it's wrapped in result
                elif isinstance(msg, dict) and "result" in msg:
                    result = msg.get("result", {})
                    yield result
                else:
                    logger.warning(f"Unrecognized message format: {msg}")
                    yield msg  # Yield it anyway to let the client handle it
                    
            except Exception as e:
                logger.error(f"Failed to process event: {e}")
                logger.debug(f"Problematic message: {msg}")
                # Try to yield the raw message anyway
                yield msg

    async def resubscribe(
        self, params: TaskQueryParams,
    ) -> AsyncIterator[Union[Dict, TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        """
        Call tasks/resubscribe and stream remaining events.
        Requires a transport that supports streaming.
        """
        try:
            iterator = self.transport.stream()
        except NotImplementedError:
            raise NotImplementedError("Streaming requires transport.stream() support")

        payload = params.model_dump(mode="json", exclude_none=True, by_alias=True)
        await self.transport.call("tasks/resubscribe", payload)
        
        # Log the resubscribe task ID for debugging
        logger.debug(f"Resubscribing to task ID: {params.id}")

        # Use the same event processing logic as send_subscribe
        async for msg in iterator:
            try:
                logger.debug(f"Received event message: {msg}")
                
                # Check if this is a tasks/event notification
                if isinstance(msg, dict) and msg.get("method") == "tasks/event":
                    # Extract params from the notification
                    params = msg.get("params", {})
                    yield params
                # If it's the event data directly
                elif isinstance(msg, dict) and ("status" in msg or "artifact" in msg):
                    yield msg
                # If it's wrapped in result
                elif isinstance(msg, dict) and "result" in msg:
                    result = msg.get("result", {})
                    yield result
                else:
                    logger.warning(f"Unrecognized message format: {msg}")
                    yield msg  # Yield it anyway to let the client handle it
                    
            except Exception as e:
                logger.error(f"Failed to process event: {e}")
                logger.debug(f"Problematic message: {msg}")
                # Try to yield the raw message anyway
                yield msg