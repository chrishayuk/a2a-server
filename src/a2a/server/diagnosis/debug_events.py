# File: a2a/server/diagnosis/debug_events.py
import asyncio
import json
import logging
import inspect
import os
from functools import wraps
from fastapi.encoders import jsonable_encoder

# Configure more detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)

# Set specific loggers to DEBUG
loggers_to_debug = [
    'a2a.server.pubsub',
    'a2a.server.tasks.task_manager',
    'a2a.server.transport.sse',
    'a2a.server.transport.http',
    'a2a.server.tasks.handlers.google_adk_handler',
    'a2a.server.tasks.handlers.adk_agent_adapter',
]

for logger_name in loggers_to_debug:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

# Add this to your EventBus class to add more detailed logging
def add_event_tracing(event_bus):
    """Enhance event bus with detailed event tracing."""
    original_publish = event_bus.publish
    original_subscribe = event_bus.subscribe
    
    @wraps(original_publish)
    async def traced_publish(event):
        """Wrap the publish method to add detailed event tracing."""
        try:
            # Format event for logging
            safe_payload = jsonable_encoder(event, exclude_none=True)
            event_json = json.dumps(safe_payload, indent=2)
            
            # Log detailed event info
            logger = logging.getLogger('a2a.server.pubsub')
            logger.debug(f"Publishing event: {type(event).__name__}")
            logger.debug(f"Event data: {event_json}")
            
            # Call original publish
            await original_publish(event)
        except Exception as e:
            logger = logging.getLogger('a2a.server.pubsub')
            logger.error(f"Error in event tracing: {e}")
            # Still publish even if tracing fails
            await original_publish(event)
    
    @wraps(original_subscribe)
    def traced_subscribe():
        """Wrap the subscribe method to add tracing."""
        queue = original_subscribe()
        logger = logging.getLogger('a2a.server.pubsub')
        logger.debug(f"New subscription created (total: {len(event_bus._queues)})")
        return queue
    
    # Replace the methods
    event_bus.publish = traced_publish
    event_bus.subscribe = traced_subscribe
    
    # Add diagnostic info
    logger = logging.getLogger('a2a.server.pubsub')
    logger.info(f"Enhanced EventBus with tracing")
    
    return event_bus



def trace_task_manager(task_manager):
    """Enhance TaskManager with detailed tracing."""
    original_create_task = task_manager.create_task
    
    @wraps(original_create_task)
    async def traced_create_task(*args, **kwargs):
        logger = logging.getLogger('a2a.server.tasks.task_manager')
        # Log the handler name if provided
        handler = kwargs.get('handler_name') or kwargs.get('handler')
        logger.debug(f"Creating task with handler: {handler}")
        
        try:
            task = await original_create_task(*args, **kwargs)
            logger.debug(f"Task created: {task.id}")
            return task
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            raise
    
    # Replace just the create_task method
    task_manager.create_task = traced_create_task
    
    logger = logging.getLogger('a2a.server.tasks.task_manager')
    logger.info(f"Enhanced TaskManager with tracing")
    
    return task_manager


# Function to trace handler processing
def trace_handler_methods(handler):
    """Add tracing to handler methods."""
    original_process_task = handler.process_task
    
    @wraps(original_process_task)
    async def traced_process_task(task_id, message, session_id=None):
        logger = logging.getLogger(f'a2a.server.tasks.handlers.{handler.name}')
        logger.debug(f"Handler {handler.name} processing task {task_id}")
        
        # We can't use traditional tracing for async generators
        # Instead, we'll wrap the generator and log each yielded value
        try:
            async for event in original_process_task(task_id, message, session_id):
                event_type = type(event).__name__
                logger.debug(f"Handler {handler.name} yielded {event_type} for task {task_id}")
                yield event
                
            logger.debug(f"Handler {handler.name} completed task {task_id}")
        except Exception as e:
            logger.error(f"Error in handler {handler.name} processing task {task_id}: {e}")
            raise
    
    # Replace the method
    handler.process_task = traced_process_task
    
    return handler


# Function to verify handler registration
def verify_handlers(task_manager):
    """Check that all handlers are properly registered."""
    logger = logging.getLogger('a2a.server.debug_events')
    
    handlers = task_manager.get_handlers()
    logger.info(f"Registered handlers: {handlers}")
    
    default = task_manager.get_default_handler()
    logger.info(f"Default handler: {default}")
    
    # Attempt to retrieve each handler to verify
    for name in handlers:
        try:
            handler = task_manager.get_handler(name)
            logger.info(f"Successfully retrieved handler '{name}': {handler.__class__.__name__}")
            
            # Add tracing to each handler
            trace_handler_methods(handler)
            
        except Exception as e:
            logger.error(f"Error retrieving handler '{name}': {e}")
    
    return task_manager

# Toggle environment variable to enable debug
def enable_debug():
    """Set environment variables to enable more verbose debugging."""
    os.environ["DEBUG_A2A"] = "1"
    os.environ["DEBUG_LEVEL"] = "DEBUG"
