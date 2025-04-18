# File: src/a2a/server/transport/http.py

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from a2a.json_rpc.protocol import JSONRPCProtocol


def setup_http(app: FastAPI, protocol: JSONRPCProtocol) -> None:
    @app.post("/rpc")
    async def handle_rpc(request: Request):
        # Parse incoming JSON-RPC payload
        payload = await request.json()
        # Dispatch asynchronously
        raw_response = await protocol._handle_raw_async(payload)
        if raw_response is None:
            # Notification: no content
            return JSONResponse(status_code=204)
        # Convert any Pydantic models or enums to JSON-serializable structures
        content = jsonable_encoder(raw_response)
        return JSONResponse(content)
