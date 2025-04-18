# File: a2a/client/transport/sse.py

import json
import uuid
import logging
import asyncio
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from a2a.json_rpc.transport import JSONRPCTransport
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.models import Json

logger = logging.getLogger("a2a-client.sse")

class JSONRPCSSEClient(JSONRPCTransport):
    """
    JSON-RPC over HTTP + SSE for streaming events.
    Sends normal RPCs via POST and listens to a separate /events SSE stream.
    """

    def __init__(
        self,
        endpoint: str,
        sse_endpoint: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.endpoint = endpoint
        # default SSE endpoint if not provided
        self.sse_endpoint = sse_endpoint or endpoint.rstrip("/").rsplit("/", 1)[0] + "/events"
        self._client = httpx.AsyncClient(timeout=timeout)
        # Store active stream response for proper cleanup
        self._active_response = None
        # Create a flag to signal shutdown
        self._shutdown = False
        
    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request (tasks/sendSubscribe, tasks/resubscribe, etc.)."""
        envelope: Json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            # give it an ID so server returns an RPC response
            "id": str(uuid.uuid4()),
        }
        
        try:
            resp = await self._client.post(self.endpoint, json=envelope)
            resp.raise_for_status()
        except httpx.ConnectError:
            logger.error(f"Cannot connect to RPC endpoint at {self.endpoint}")
            logger.error("Please ensure the A2A server is running.")
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.error(f"RPC endpoint {self.endpoint} not found.")
                logger.error("Please check the endpoint URL and ensure the server is running.")
            raise

        # Some methods (sendSubscribe/resubscribe) may return 204 No Content
        if resp.status_code == 204 or not resp.content:
            return None

        data = resp.json()
        if data.get("error"):
            err = data["error"]
            raise JSONRPCError(message=err.get("message"), data=err.get("data"))
        return data.get("result")

    def stream(self) -> AsyncIterator[Json]:
        """
        Connects to the SSE endpoint and yields each `data: { ... }` line
        as a dict. Cleans up cleanly on stream closure.
        """
        self._shutdown = False  # Reset shutdown flag
        
        async def _aiter():
            headers = {"Accept": "text/event-stream"}
            try:
                async with self._client.stream(
                    "GET", self.sse_endpoint, headers=headers
                ) as resp:
                    self._active_response = resp  # Store for cleanup
                    resp.raise_for_status()
                    logger.debug(f"Connected to SSE endpoint at {self.sse_endpoint}")
                    
                    try:
                        async for line in resp.aiter_lines():
                            # Check if shutdown requested
                            if self._shutdown:
                                logger.debug("Stream shutdown requested, stopping iteration")
                                break
                                
                            # Only handle SSE data lines
                            if not line.startswith("data:"):
                                continue
                            raw = line[len("data:"):].strip()
                            try:
                                event_data = json.loads(raw)
                                # Log the raw event data for debugging
                                logger.debug(f"Received SSE event: {event_data}")
                                yield event_data
                            except json.JSONDecodeError as e:
                                logger.warning(f"Malformed SSE data: {e}")
                                continue
                    except GeneratorExit:
                        # Handle generator close gracefully
                        logger.debug("SSE generator exiting")
                        self._shutdown = True
                        return
                    except asyncio.CancelledError:
                        # Handle task cancellation 
                        logger.debug("SSE stream task cancelled")
                        self._shutdown = True
                        return
                    except httpx.ReadTimeout:
                        logger.error("SSE stream read timeout")
                        raise
                    except httpx.ReadError as e:
                        logger.error(f"SSE stream read error: {e}")
                        raise
                    except Exception as e:
                        logger.error(f"Error during SSE streaming: {e}")
                        raise
            except httpx.ConnectError:
                logger.error(f"Cannot connect to SSE endpoint at {self.sse_endpoint}")
                logger.error("Please ensure the server is running with the SSE endpoint enabled.")
                raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.error(f"SSE endpoint {self.sse_endpoint} not found")
                    logger.error("Please check the URL and ensure the server is running correctly.")
                raise
            finally:
                # Clear active response on exit
                self._active_response = None

        return _aiter()

    async def close(self) -> None:
        """Close the HTTP client and any active streams."""
        # Signal stream to shut down
        self._shutdown = True
        
        # Give any active stream a chance to close gracefully
        if self._active_response is not None:
            try:
                # Try to close the underlying connection if possible
                if hasattr(self._active_response, 'aclose'):
                    await self._active_response.aclose()
            except Exception as e:
                logger.debug(f"Error closing SSE response: {e}")
        
        # Close the client
        await self._client.aclose()