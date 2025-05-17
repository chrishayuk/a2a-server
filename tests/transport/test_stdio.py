# In tests/transport/test_stdio.py

import pytest
import json
from a2a_server.transport.stdio import handle_stdio_message
from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_server.tasks.task_manager import TaskManager
from a2a_server.methods import register_methods
from a2a_server.pubsub import EventBus
from a2a_json_rpc.spec import TaskState
from a2a_server.tasks.handlers.echo_handler import EchoHandler

@pytest.fixture
def protocol_manager():
    """Set up protocol with task manager for stdio tests."""
    event_bus = EventBus()
    manager = TaskManager(event_bus)
    # Make sure to register a default handler
    manager.register_handler(EchoHandler(), default=True)
    
    protocol = JSONRPCProtocol()
    register_methods(protocol, manager)
    return protocol, manager

def test_stdio_send_and_get(protocol_manager):
    """
    Sending a 'tasks/send' request over stdio returns a valid Task with submitted state.
    """
    protocol, _ = protocol_manager
    send_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tasks/send",
        "params": {
            "id": "ignored",
            "sessionId": None,
            "message": {"role": "user", "parts": [{"type": "text", "text": "Hello stdio"}]}
        }
    }
    raw = json.dumps(send_req)
    resp_str = handle_stdio_message(protocol, raw)
    assert resp_str is not None
    resp = json.loads(resp_str)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    # The state should be the string value of the enum
    assert result["status"]["state"] == TaskState.submitted.value


def test_stdio_cancel(protocol_manager):
    """
    Canceling a task over stdio returns no result and updates state to canceled.
    """
    protocol, _ = protocol_manager
    # Create a task first
    send_req = {
        "jsonrpc": "2.0", "id": 10, "method": "tasks/send",
        "params": {"id": "ignored", "sessionId": None,
                "message": {"role": "user", "parts": [{"type": "text", "text": "Cancel"}]}}
    }
    send_res = json.loads(handle_stdio_message(protocol, json.dumps(send_req)))
    task_id = send_res["result"]["id"]
    
    # Then cancel it
    cancel_req = {
        "jsonrpc": "2.0", "id": 11, "method": "tasks/cancel",
        "params": {"id": task_id}
    }
    cancel_res = json.loads(handle_stdio_message(protocol, json.dumps(cancel_req)))
    assert cancel_res["id"] == 11
    assert cancel_res["result"] is None

    # Verify state with get
    get_req = {
        "jsonrpc": "2.0", "id": 12, "method": "tasks/get",
        "params": {"id": task_id}
    }
    get_res = json.loads(handle_stdio_message(protocol, json.dumps(get_req)))
    assert get_res["result"]["status"]["state"] == TaskState.canceled.value


def test_stdio_notification(protocol_manager):
    """Notification (no id) returns None."""
    protocol, _ = protocol_manager
    notification = {
        "jsonrpc": "2.0",
        "method": "tasks/ping",
        "params": {}
    }
    assert handle_stdio_message(protocol, json.dumps(notification)) is None