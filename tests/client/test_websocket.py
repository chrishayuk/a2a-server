import pytest
from a2a.client.transport.websocket import JSONRPCWebSocketClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError

class FakeWS:
    def __init__(self, messages):
        self.messages = messages
        self.sent = []
        self.is_closed = False

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        return self.messages.pop(0)

    async def aclose(self):
        self.is_closed = True

@pytest.mark.asyncio
async def test_ws_call_success():
    client = JSONRPCWebSocketClient("ws://test")
    ws = FakeWS([{"jsonrpc": "2.0", "result": {"ok": True}, "id": None}])

    # Monkeypatch connect to set our FakeWS
    async def fake_connect():
        client._ws = ws
    client.connect = fake_connect

    result = await client.call("foo", {"a": 1})
    assert result == {"ok": True}
    assert ws.sent[0]["method"] == "foo"

@pytest.mark.asyncio
async def test_ws_call_error():
    client = JSONRPCWebSocketClient("ws://test")
    ws = FakeWS([{"jsonrpc": "2.0", "error": {"code": -32002, "message": "Cannot cancel"}, "id": None}])

    async def fake_connect():
        client._ws = ws
    client.connect = fake_connect

    with pytest.raises(JSONRPCError) as excinfo:
        await client.call("foo", {})
    assert "Cannot cancel" in str(excinfo.value)

@pytest.mark.asyncio
async def test_ws_notify_and_stream():
    client = JSONRPCWebSocketClient("ws://test")
    ws = FakeWS([
        {"jsonrpc": "2.0", "method": "stream", "params": None, "id": None},
        {"jsonrpc": "2.0", "result": {"data": 1}, "id": None}
    ])

    async def fake_connect():
        client._ws = ws
    client.connect = fake_connect

    # Test notify
    await client.notify("bar", {"x": 2})
    assert ws.sent[-1]["method"] == "bar"

    # Test stream
    outputs = []
    async for msg in client.stream():
        outputs.append(msg)
        if len(outputs) == 2:
            break
    assert outputs[1]["result"]["data"] == 1

@pytest.mark.asyncio
async def test_ws_close():
    client = JSONRPCWebSocketClient("ws://test")
    ws = FakeWS([])
    async def fake_connect(): client._ws = ws
    client.connect = fake_connect
    await client.connect()
    await client.close()
    assert ws.is_closed
