# File: a2a_server/transport/ws.py

import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_server.pubsub import EventBus


def setup_ws(app: FastAPI, protocol: JSONRPCProtocol, event_bus: EventBus) -> None:
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
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
                    event = listener.result()
                    # Serialize event payload
                    params = jsonable_encoder(event.model_dump(exclude_none=True))
                    # Send as JSON-RPC notification
                    await ws.send_json({
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": params,
                    })
                    receiver.cancel()
                else:
                    msg = receiver.result()
                    # Dispatch JSON-RPC request asynchronously
                    raw_response = await protocol._handle_raw_async(msg)
                    if raw_response is not None:
                        # Serialize and send the response
                        content = jsonable_encoder(raw_response)
                        await ws.send_json(content)
                    listener.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            event_bus.unsubscribe(queue)