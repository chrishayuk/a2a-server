# File: src/a2a/server/transport/sse.py
"""
Server-Sent Events (SSE) transport for the A2A server.
Defines SSE endpoints for default handler and specific handlers.
"""
import json
from typing import Dict, Optional, AsyncGenerator, List
from fastapi import FastAPI, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
import logging

from a2a.server.pubsub import EventBus
from a2a.server.tasks.task_manager import TaskManager

logger = logging.getLogger(__name__)

def setup_sse(app: FastAPI, event_bus: EventBus, task_manager: TaskManager) -> None:
    """
    Set up SSE endpoints with direct handler mounting:
    - /events for default handler
    - /{handler_name}/events for specific handlers
    """
    @app.get("/events", summary="Stream task status & artifact updates via SSE")
    async def sse_default_endpoint(
        request: Request,
        task_ids: Optional[List[str]] = Query(None)
    ):
        """SSE endpoint for the default handler."""
        return await _create_sse_response(event_bus, task_ids)
    
    # Get all registered handlers
    all_handlers = task_manager.get_handlers()
    
    # Create handler-specific SSE endpoints
    for handler_name in all_handlers:
        # Create a function to properly capture handler_name in closure
        def create_sse_endpoint(name):
            async def handler_sse_endpoint(
                request: Request,
                task_ids: Optional[List[str]] = Query(None)
            ):
                """SSE endpoint for a specific handler."""
                logger.debug(f"SSE connection established for handler '{name}'")
                # Could implement handler-specific filtering here if needed
                return await _create_sse_response(event_bus, task_ids)
            return handler_sse_endpoint
        
        # Register the endpoint with a concrete path
        endpoint = create_sse_endpoint(handler_name)
        app.get(f"/{handler_name}/events", summary=f"Stream events for {handler_name}")(endpoint)
        logger.debug(f"Registered SSE endpoint for handler '{handler_name}'")


async def _create_sse_response(
    event_bus: EventBus,
    task_ids: Optional[List[str]] = None
) -> StreamingResponse:
    """
    Create an SSE streaming response.
    
    Args:
        event_bus: The event bus to subscribe to
        task_ids: Optional list of task IDs to filter events
    
    Returns:
        StreamingResponse with SSE events
    """
    # Subscribe to event bus
    queue = event_bus.subscribe()
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from the event bus queue."""
        try:
            while True:
                # Wait for next published event
                event = await queue.get()
                
                # Filter by task ID if specified
                if task_ids and hasattr(event, 'id') and event.id not in task_ids:
                    continue
                
                # Convert to JSON-serializable format
                safe_payload = jsonable_encoder(event, exclude_none=True)
                data_str = json.dumps(safe_payload)
                
                # Yield in proper SSE format
                yield f"data: {data_str}\n\n"
        finally:
            # Clean up subscription on disconnect
            event_bus.unsubscribe(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )