import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

# a2a imports
from a2a.server.pubsub import EventBus


def setup_sse(app: FastAPI, event_bus: EventBus) -> None:
    """
    Attach an SSE endpoint to the FastAPI app that streams
    TaskStatusUpdateEvent and TaskArtifactUpdateEvent messages
    to all subscribers. Uses app.state.event_bus so tests can override it.
    """
    @app.get("/events")
    async def sse_endpoint():
        # Use the EventBus attached to app.state
        eb: EventBus = app.state.event_bus
        queue = eb.subscribe()

        async def event_generator():
            try:
                while True:
                    # Wait for the next event
                    event = await queue.get()
                    # Serialize the Pydantic model to JSON
                    payload = json.dumps(event.model_dump(exclude_none=True))
                    # Yield in SSE format
                    yield f"data: {payload}\n\n"
            finally:
                # Clean up when client disconnects
                eb.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )
