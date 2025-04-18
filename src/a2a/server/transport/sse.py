# File: src/a2a/server/transport/sse.py

import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder

# a2a imports
from a2a.server.pubsub import EventBus


def setup_sse(app: FastAPI, event_bus: EventBus) -> None:
    """
    Attach an SSE endpoint to the FastAPI app that streams
    TaskStatusUpdateEvent and TaskArtifactUpdateEvent messages
    to all subscribers.
    """
    @app.get("/events", summary="Stream task status & artifact updates via SSE")
    async def sse_endpoint():
        # Subscribe returns an asyncio.Queue of events
        queue = event_bus.subscribe()

        async def event_generator():
            try:
                while True:
                    # Wait for next published event
                    event = await queue.get()
                    # Convert Pydantic model (and its enums/timestamps) into JSON-serializable dict
                    safe_payload = jsonable_encoder(event, exclude_none=True)
                    # Dump that dict into a JSON string
                    data_str = json.dumps(safe_payload)
                    # Yield in proper SSE "data: " format
                    yield f"data: {data_str}\n\n"
            finally:
                # Clean up subscription on disconnect
                event_bus.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )
