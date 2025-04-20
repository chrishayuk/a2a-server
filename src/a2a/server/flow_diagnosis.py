# File: a2a/server/flow_diagnosis.py
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

# Function to trace event flow in HTTP transport
def trace_http_transport(setup_http_func):
    """Wrap HTTP transport setup to trace event flow."""
    original_setup = setup_http_func
    
    def traced_setup_http(app, protocol, task_manager, event_bus=None):
        logger.info("Setting up HTTP transport with tracing")
        
        # Add diagnostic endpoint
        @app.get("/debug/event-flow")
        async def debug_event_flow():
            """Diagnostic endpoint to check event flow."""
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
        
        # Replace handle_sendsubscribe_streaming if it exists
        if hasattr(setup_http_func, "__module__"):
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
                            if hasattr(result, "media_type"):
                                logger.info(f"Response media_type: {result.media_type}")
                            return result
                        except Exception as e:
                            logger.error(f"Error in handle_sendsubscribe_streaming: {e}", exc_info=True)
                            raise
                    
                    # Replace the function
                    module.handle_sendsubscribe_streaming = traced_handler
                    logger.info("Replaced handle_sendsubscribe_streaming with traced version")
            except (ImportError, AttributeError) as e:
                logger.warning(f"Could not trace handle_sendsubscribe_streaming: {e}")
        
        # Call original setup
        return original_setup(app, protocol, task_manager, event_bus)
    
    return traced_setup_http

# Function to trace event flow in SSE transport
def trace_sse_transport(setup_sse_func):
    """Wrap SSE transport setup to trace event flow."""
    original_setup = setup_sse_func
    
    def traced_setup_sse(app, event_bus, task_manager):
        logger.info("Setting up SSE transport with tracing")
        
        # Replace _create_sse_response if it exists
        if hasattr(setup_sse_func, "__module__"):
            module_name = setup_sse_func.__module__
            try:
                module = __import__(module_name, fromlist=["_create_sse_response"])
                if hasattr(module, "_create_sse_response"):
                    original_creator = module._create_sse_response
                    
                    async def traced_creator(event_bus, task_ids=None):
                        logger.info(f"Creating SSE response for task_ids: {task_ids}")
                        
                        # Create a copy of event_bus.subscribe
                        original_subscribe = event_bus.subscribe
                        
                        def traced_subscribe():
                            logger.info("SSE subscribing to event bus")
                            queue = original_subscribe()
                            logger.info(f"SSE subscription created (total: {len(event_bus._queues)})")
                            
                            # Trace the original queue.get method
                            original_get = queue.get
                            
                            async def traced_get():
                                logger.info("SSE waiting for event")
                                event = await original_get()
                                event_type = type(event).__name__
                                
                                try:
                                    event_id = getattr(event, "id", None)
                                    logger.info(f"SSE received event: {event_type} for task {event_id}")
                                    
                                    # Log more details for specific event types
                                    if hasattr(event, "status"):
                                        logger.info(f"Status event state: {event.status.state}")
                                        if hasattr(event.status, "message") and event.status.message:
                                            msg_parts = len(getattr(event.status.message, "parts", []))
                                            logger.info(f"Status has message with {msg_parts} parts")
                                    elif hasattr(event, "artifact"):
                                        artifact_parts = len(getattr(event.artifact, "parts", []))
                                        logger.info(f"Artifact event has {artifact_parts} parts")
                                except Exception as e:
                                    logger.error(f"Error examining event: {e}")
                                
                                return event
                            
                            # Replace queue.get
                            queue.get = traced_get
                            
                            return queue
                        
                        # Replace event_bus.subscribe temporarily
                        event_bus.subscribe = traced_subscribe
                        
                        try:
                            response = await original_creator(event_bus, task_ids)
                            logger.info(f"SSE response created with media_type: {response.media_type}")
                            return response
                        finally:
                            # Restore original subscribe
                            event_bus.subscribe = original_subscribe
                    
                    # Replace the function
                    module._create_sse_response = traced_creator
                    logger.info("Replaced _create_sse_response with traced version")
            except (ImportError, AttributeError) as e:
                logger.warning(f"Could not trace _create_sse_response: {e}")
        
        # Call original setup
        return original_setup(app, event_bus, task_manager)
    
    return traced_setup_sse

# Function to trace event bus operations
def trace_event_bus(event_bus):
    """Add detailed tracing to event bus operations."""
    # Replace publish
    original_publish = event_bus.publish
    
    async def traced_publish(event):
        event_type = type(event).__name__
        event_id = getattr(event, "id", None)
        logger.info(f"EventBus publishing {event_type} for task {event_id}")
        
        # Log more details for specific event types
        if hasattr(event, "status"):
            logger.info(f"Status event state: {event.status.state}")
            if hasattr(event.status, "message") and event.status.message:
                msg_parts = len(getattr(event.status.message, "parts", []))
                logger.info(f"Status has message with {msg_parts} parts")
                
                # Log first part content if it's text
                if msg_parts > 0 and hasattr(event.status.message, "parts"):
                    first_part = event.status.message.parts[0]
                    if hasattr(first_part, "type") and first_part.type == "text":
                        text = getattr(first_part, "text", "")
                        if text:
                            preview = text[:100] + ("..." if len(text) > 100 else "")
                            logger.info(f"Message text: {preview}")
        elif hasattr(event, "artifact"):
            artifact_parts = len(getattr(event.artifact, "parts", []))
            logger.info(f"Artifact event has {artifact_parts} parts")
            
            # Log first part content if it's text
            if artifact_parts > 0 and hasattr(event.artifact, "parts"):
                first_part = event.artifact.parts[0]
                if hasattr(first_part, "type") and first_part.type == "text":
                    text = getattr(first_part, "text", "")
                    if text:
                        preview = text[:100] + ("..." if len(text) > 100 else "")
                        logger.info(f"Artifact text: {preview}")
        
        # Count subscribers
        subscribers = len(event_bus._queues)
        logger.info(f"Publishing to {subscribers} subscribers")
        
        # Call original
        await original_publish(event)
        logger.info(f"Event {event_type} published successfully")
    
    # Replace the method
    event_bus.publish = traced_publish
    
    # Count subscriptions periodically
    async def monitor_subscriptions():
        while True:
            subscribers = len(event_bus._queues)
            logger.info(f"EventBus has {subscribers} active subscriptions")
            await asyncio.sleep(5)
    
    # Start monitoring in background
    try:
        loop = asyncio.get_event_loop()
        task = loop.create_task(monitor_subscriptions())
    except RuntimeError:
        # No event loop, skip monitoring
        pass
    
    return event_bus

# Apply all tracers
def apply_flow_tracing(app_module=None, http_module=None, sse_module=None, event_bus=None):
    """Apply all flow tracers to the given modules and event bus."""
    if app_module:
        logger.info("Applying tracing to app module")
    
    if http_module:
        logger.info("Applying tracing to HTTP transport")
        if hasattr(http_module, "setup_http"):
            http_module.setup_http = trace_http_transport(http_module.setup_http)
    
    if sse_module:
        logger.info("Applying tracing to SSE transport")
        if hasattr(sse_module, "setup_sse"):
            sse_module.setup_sse = trace_sse_transport(sse_module.setup_sse)
    
    if event_bus:
        logger.info("Applying tracing to event bus")
        trace_event_bus(event_bus)
    
    logger.info("Flow tracing applied")

# Usage example:
# from a2a.server import app
# from a2a.server.transport import http, sse
# from a2a.server.flow_diagnosis import apply_flow_tracing
# 
# # In app.py before creating FastAPI app:
# event_bus = EventBus()
# apply_flow_tracing(app, http, sse, event_bus)