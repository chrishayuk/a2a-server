# File: a2a_server/transport/sse.py
"""
Server-Sent Events (SSE) transport for the A2A server.
Modified to ensure events are compatible with the A2A client.
"""
import json
from typing import Dict, Optional, AsyncGenerator, List
from fastapi import FastAPI, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
import logging

from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_manager import TaskManager

logger = logging.getLogger(__name__)

async def _create_sse_response(
    event_bus: EventBus,
    task_ids: Optional[List[str]] = None
) -> StreamingResponse:
    """
    Create an SSE streaming response compatible with A2A clients.
    
    Args:
        event_bus: The event bus to subscribe to
        task_ids: Optional list of task IDs to filter events
    
    Returns:
        StreamingResponse with SSE events in A2A client format
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
                
                # Convert to JSON-serializable format with proper formatting for client
                event_data = jsonable_encoder(event, exclude_none=True)
                
                # Check the event type to format it appropriately for the client
                event_type = type(event).__name__
                
                # For TaskStatusUpdateEvent
                if hasattr(event, 'status'):
                    # Extract and format message if available
                    message = None
                    if hasattr(event.status, 'message') and event.status.message:
                        message = jsonable_encoder(event.status.message, exclude_none=True)
                    
                    # Create a properly structured client event
                    client_event = {
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": {
                            "type": "status",
                            "id": event.id,
                            "status": {
                                "state": str(event.status.state),
                                "timestamp": event.status.timestamp.isoformat() if hasattr(event.status, 'timestamp') else None,
                                "message": message
                            },
                            "final": event.final if hasattr(event, 'final') else False
                        }
                    }
                # For TaskArtifactUpdateEvent
                elif hasattr(event, 'artifact'):
                    client_event = {
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": {
                            "type": "artifact",
                            "id": event.id,
                            "artifact": jsonable_encoder(event.artifact, exclude_none=True)
                        }
                    }
                # Default fallback
                else:
                    client_event = {
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": event_data
                    }
                
                # Serialize to JSON
                data_str = json.dumps(client_event)
                logger.debug(f"Sending SSE event: {data_str[:200]}...")
                
                # Yield in proper SSE format
                yield f"data: {data_str}\n\n"
        finally:
            # Clean up subscription on disconnect
            event_bus.unsubscribe(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # For Nginx
        }
    )

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