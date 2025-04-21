# File: a2a_server/routes/debug.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse

def register_debug_routes(app: FastAPI, event_bus, task_manager):
    @app.get("/debug/event-bus")
    async def _debug_event_bus():
        return {
            "status": "ok",
            "subscriptions": len(event_bus._queues),
            "handlers": task_manager.get_handlers(),
            "default_handler": task_manager.get_default_handler(),
        }

    @app.post("/debug/test-event/{task_id}")
    async def _debug_test_event(task_id: str, message: str = "Test message"):
        # pull everything from the JSON‑RPC spec module
        from a2a_json_rpc.spec import (
            TaskStatus, TaskState, Message, Role, TextPart, TaskStatusUpdateEvent
        )

        # build a fake "completed" message and publish it
        text_part = TextPart(type="text", text=message)
        test_message = Message(role=Role.agent, parts=[text_part])
        status = TaskStatus(state=TaskState.completed)
        setattr(status, "message", test_message)

        event = TaskStatusUpdateEvent(id=task_id, status=status, final=True)
        await event_bus.publish(event)

        return JSONResponse({"status": "ok", "message": "Test event published"})
