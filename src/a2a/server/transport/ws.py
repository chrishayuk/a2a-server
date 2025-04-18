# a2a/server/transport/ws.py
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# a2a imports
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.pubsub import EventBus


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
                    await ws.send_json({
                        "jsonrpc": "2.0",
                        "method": "tasks/event",
                        "params": event.model_dump(exclude_none=True),
                    })
                    receiver.cancel()
                else:
                    msg = receiver.result()
                    response = protocol.handle_raw(msg)
                    if response:
                        await ws.send_json(response)
                    listener.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            event_bus.unsubscribe(queue)