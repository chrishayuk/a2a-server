# File: src/a2a/server/transport/http.py
"""
HTTP JSON-RPC transport for the A2A server.
Defines JSON-RPC endpoints for default handler and specific handlers.
"""
from typing import Dict, List, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
import logging

from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.tasks.task_handler import TaskHandler
from a2a.server.tasks.task_manager import TaskManager

logger = logging.getLogger(__name__)

def setup_http(app: FastAPI, protocol: JSONRPCProtocol, task_manager: TaskManager) -> None:
    """
    Set up HTTP JSON-RPC endpoints with direct handler mounting:
    - /rpc for default handler
    - /{handler_name}/rpc for specific handlers
    """
    # Default handler endpoint
    @app.post("/rpc")
    async def handle_default_rpc(request: Request):
        """Handle JSON-RPC requests using the default handler."""
        payload = await request.json()
        raw_response = await protocol._handle_raw_async(payload)
        if raw_response is None:
            return Response(status_code=204)
        content = jsonable_encoder(raw_response)
        return JSONResponse(content=content)
    
    # Get all registered handlers
    all_handlers = task_manager.get_handlers()
    
    # Create handler-specific endpoints
    for handler_name in all_handlers:
        # Create a function to properly capture handler_name in closure
        def create_handler_endpoint(name):
            async def handler_rpc_endpoint(request: Request):
                """Handle JSON-RPC requests for a specific handler."""
                payload = await request.json()
                
                # If this is a task-related method, inject handler selection
                if isinstance(payload, dict) and "method" in payload and "params" in payload:
                    method = payload["method"]
                    if method in ("tasks/send", "tasks/sendSubscribe"):
                        # Add or override handler parameter
                        if isinstance(payload["params"], dict):
                            payload["params"]["handler"] = name
                
                raw_response = await protocol._handle_raw_async(payload)
                if raw_response is None:
                    return Response(status_code=204)
                content = jsonable_encoder(raw_response)
                return JSONResponse(content=content)
            return handler_rpc_endpoint
        
        # Register the endpoint with a concrete path
        endpoint = create_handler_endpoint(handler_name)
        app.post(f"/{handler_name}/rpc")(endpoint)
        logger.debug(f"Registered RPC endpoint for handler '{handler_name}'")