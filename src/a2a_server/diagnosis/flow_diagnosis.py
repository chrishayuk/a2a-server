# File: a2a_server/diagnosis/flow_diagnosis.py
"""
Diagnostic tool to trace event flow through the A2A system.
"""
import asyncio
import json
import logging
import inspect
from fastapi.encoders import jsonable_encoder
from typing import Any, Dict, Optional, List, Callable, Awaitable, AsyncGenerator, Generator

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def trace_http_transport(setup_http_func):
    """Wrap HTTP transport setup to trace event flow."""
    original_setup = setup_http_func

    def traced_setup_http(app, protocol, task_manager, event_bus=None):
        logger.info("Setting up HTTP transport with tracing")

        @app.get("/debug/event-flow")
        async def debug_event_flow():
            return {
                "status": "ok",
                "components": {
                    "event_bus": {
                        "type": type(event_bus).__name__,
                        "subscriptions": len(getattr(event_bus, "_queues", [])),
                    },
                    "task_manager": {
                        "type": type(task_manager).__name__,
                        "handlers": list(task_manager.get_handlers().keys()),
                        "default_handler": task_manager.get_default_handler(),
                        "active_tasks": len(getattr(task_manager, "_tasks", {})),
                    },
                    "protocol": {
                        "type": type(protocol).__name__,
                        "methods": list(getattr(protocol, "_methods", {}).keys()),
                    }
                }
            }

        # patch handle_sendsubscribe_streaming if present
        module_name = setup_http_func.__module__
        try:
            module = __import__(module_name, fromlist=["handle_sendsubscribe_streaming"])
            if hasattr(module, "handle_sendsubscribe_streaming"):
                original_handler = module.handle_sendsubscribe_streaming

                async def traced_handler(*args, **kwargs):
                    logger.info("Tracing handle_sendsubscribe_streaming call")
                    try:
                        result = await original_handler(*args, **kwargs)
                        logger.info(f"handle_sendsubscribe_streaming returned: {type(result).__name__}")
                        return result
                    except Exception as e:
                        logger.error(f"Error in handle_sendsubscribe_streaming: {e}", exc_info=True)
                        raise

                module.handle_sendsubscribe_streaming = traced_handler
                logger.info("Replaced handle_sendsubscribe_streaming with traced version")
        except Exception:
            pass

        return original_setup(app, protocol, task_manager, event_bus)

    return traced_setup_http

def trace_sse_transport(setup_sse_func):
    """Wrap SSE transport setup to trace event flow."""
    original_setup = setup_sse_func

    def traced_setup_sse(app, event_bus, task_manager):
        logger.info("Setting up SSE transport with tracing")

        module_name = setup_sse_func.__module__
        try:
            module = __import__(module_name, fromlist=["_create_sse_response"])
            if hasattr(module, "_create_sse_response"):
                original_creator = module._create_sse_response

                async def traced_creator(event_bus, task_ids=None):
                    logger.info(f"Creating SSE response for task_ids: {task_ids}")
                    original_subscribe = event_bus.subscribe

                    def traced_subscribe():
                        logger.info("SSE subscribing to event bus")
                        queue = original_subscribe()
                        logger.info(f"SSE subscription created (total: {len(event_bus._queues)})")

                        original_get = queue.get

                        async def traced_get():
                            logger.info("SSE waiting for event")
                            event = await original_get()
                            evtype = type(event).__name__
                            logger.info(f"SSE received event: {evtype} for task {getattr(event, 'id', None)}")
                            return event

                        queue.get = traced_get
                        return queue

                    event_bus.subscribe = traced_subscribe
                    try:
                        response = await original_creator(event_bus, task_ids)
                        logger.info(f"SSE response created with media_type: {response.media_type}")
                        return response
                    finally:
                        event_bus.subscribe = original_subscribe

                module._create_sse_response = traced_creator
                logger.info("Replaced _create_sse_response with traced version")
        except Exception:
            pass

        return original_setup(app, event_bus, task_manager)

    return traced_setup_sse

def trace_event_bus(event_bus):
    """Add detailed tracing to event bus operations, return monitor coroutine."""
    original_publish = event_bus.publish

    async def traced_publish(event):
        etype = type(event).__name__
        eid = getattr(event, "id", None)
        logger.info(f"EventBus publishing {etype} for task {eid}")

        await original_publish(event)
        logger.info(f"Event {etype} published successfully")

    event_bus.publish = traced_publish

    async def monitor_subscriptions():
        try:
            while True:
                cnt = len(getattr(event_bus, "_queues", []))
                logger.info(f"EventBus has {cnt} active subscriptions")
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("monitor_subscriptions cancelled, exiting")

    # Return the coroutine function; caller will schedule it
    return monitor_subscriptions

def apply_flow_tracing(app_module=None, http_module=None, sse_module=None, event_bus=None):
    """
    Apply all flow tracers to the given modules and event bus.
    Returns a monitor coroutine (or None).
    """
    if http_module and hasattr(http_module, "setup_http"):
        logger.info("Applying tracing to HTTP transport")
        http_module.setup_http = trace_http_transport(http_module.setup_http)

    if sse_module and hasattr(sse_module, "setup_sse"):
        logger.info("Applying tracing to SSE transport")
        sse_module.setup_sse = trace_sse_transport(sse_module.setup_sse)

    monitor_coro = None
    if event_bus:
        logger.info("Applying tracing to event bus")
        monitor_coro = trace_event_bus(event_bus)

    logger.info("Flow tracing applied")
    return monitor_coro
