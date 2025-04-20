# a2a/server/transport/ws.py
"""
WebSocket transport for the A2A server.
Defines WebSocket endpoints for default handler and specific handlers.
"""
import asyncio
import json
from typing import Dict, Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import logging

from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.pubsub import EventBus
from a2a.server.tasks.task_manager import TaskManager

logger = logging.getLogger(__name__)

def setup_ws(app: FastAPI, protocol: JSONRPCProtocol, event_bus: EventBus, task_manager: TaskManager) -> None:
    """
    Set up WebSocket endpoints with direct handler mounting:
    - /ws for default handler
    - /{handler_name}/ws for specific handlers
    """
    @app.websocket("/ws")
    async def ws_default_endpoint(ws: WebSocket):
        """WebSocket endpoint for the default handler."""
        await _handle_websocket(ws, protocol, event_bus)
    
    # Get all registered handlers
    all_handlers = task_manager.get_handlers()
    
    # Create explicit WebSocket routes for each handler
    for handler_name in all_handlers:
        # We need to use a function to create a proper closure that captures handler_name
        def create_ws_handler(name):
            async def handler_ws_endpoint(websocket: WebSocket):
                """WebSocket endpoint for a specific handler."""
                logger.debug(f"WebSocket connection established for handler '{name}'")
                await _handle_websocket(websocket, protocol, event_bus, name)
            return handler_ws_endpoint
        
        # Register the websocket endpoint with a concrete path
        app.websocket(f"/{handler_name}/ws")(create_ws_handler(handler_name))
        logger.debug(f"Registered WebSocket endpoint for handler '{handler_name}'")


async def _handle_websocket(
    ws: WebSocket,
    protocol: JSONRPCProtocol,
    event_bus: EventBus,
    handler_name: Optional[str] = None
) -> None:
    """
    Handle a WebSocket connection for any handler.
    
    Args:
        ws: The WebSocket connection
        protocol: JSON-RPC protocol handler
        event_bus: Event bus for subscribing to events
        handler_name: Optional handler name to inject into requests
    """
    await ws.accept()
    queue = event_bus.subscribe()
    
    try:
        while True:
            listener = asyncio.create_task(queue.get())
            receiver = asyncio.create_task(ws.receive_json())
            done, pending = await asyncio.wait(
                {listener, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if listener in done:
                # Handle event from event bus
                event = listener.result()
                await ws.send_json({
                    "jsonrpc": "2.0",
                    "method": "tasks/event",
                    "params": event.model_dump(exclude_none=True),
                })
                receiver.cancel()
            else:
                # Handle message from client
                msg = receiver.result()
                
                # Inject handler name if specified
                if handler_name and isinstance(msg, dict):
                    if "method" in msg and "params" in msg:
                        method = msg["method"]
                        if method in ("tasks/send", "tasks/sendSubscribe"):
                            if isinstance(msg["params"], dict):
                                msg["params"]["handler"] = handler_name
                
                response = await protocol._handle_raw_async(msg)
                if response:
                    await ws.send_json(response)
                listener.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)