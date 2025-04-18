# File: src/a2a/server/transport/http.py
"""
HTTP JSON-RPC transport for the A2A server.
Defines a single POST /rpc endpoint that delegates to the JSONRPCProtocol.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder

from a2a.json_rpc.protocol import JSONRPCProtocol


def setup_http(app: FastAPI, protocol: JSONRPCProtocol) -> None:
    @app.post("/rpc")
    async def handle_rpc(request: Request):
        # Parse incoming JSON-RPC payload
        payload = await request.json()
        # Dispatch asynchronously, returning a dict or None for notifications
        raw_response = await protocol._handle_raw_async(payload)
        if raw_response is None:
            # Notification: no content
            return Response(status_code=204)
        # Serialize response dict (including enums/Pydantic models)
        content = jsonable_encoder(raw_response)
        return JSONResponse(content=content)
