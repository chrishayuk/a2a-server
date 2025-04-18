# a2a/server/app.py
from fastapi import FastAPI

# a2a imports
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.task_manager import TaskManager
from a2a.server.pubsub import EventBus
from a2a.server.methods import register_methods
from a2a.server.transport import setup_http, setup_ws, setup_sse


def create_app() -> FastAPI:
    event_bus = EventBus()
    manager = TaskManager(event_bus)
    protocol = JSONRPCProtocol()

    register_methods(protocol, manager)

    app = FastAPI()
    setup_http(app, protocol)
    setup_ws(app, protocol, event_bus)
    setup_sse(app, event_bus)

    return app

app = create_app()