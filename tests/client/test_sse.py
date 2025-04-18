import pytest
import json
from a2a.client.transport.sse import JSONRPCSSEClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError

class FakeContext:
    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def aiter_lines(self):
        for line in self.lines:
            yield line

@pytest.mark.asyncio
async def test_sse_call_and_notify():
    client = JSONRPCSSEClient("http://test", "http://test/stream")

    class FakeResp:
        def __init__(self, data):
            self._data = data
        def raise_for_status(self):
            pass
        def json(self):
            return self._data

    async def fake_post(url, json):
        return FakeResp({"jsonrpc": "2.0", "result": 42, "id": None})

    client._client.post = fake_post
    result = await client.call("foo", {"a": 1})
    assert result == 42

    async def fake_error(url, json):
        return FakeResp({"jsonrpc": "2.0", "error": {"code": -32602, "message": "Bad params"}, "id": None})
    client._client.post = fake_error
    with pytest.raises(JSONRPCError):
        await client.call("foo", {})

    async def fake_notify(url, json):
        return FakeResp({})
    client._client.post = fake_notify
    await client.notify("foo", {"x": 2})

@pytest.mark.asyncio
async def test_sse_stream():
    data1 = json.dumps({"jsonrpc": "2.0", "result": {"val": 1}})
    data2 = json.dumps({"jsonrpc": "2.0", "result": {"val": 2}})
    fake_context = FakeContext([
        "\n",
        ": comment",
        f"data: {data1}\n",
        f"data:{data2}\n",
    ])
    client = JSONRPCSSEClient("http://test", "http://test/stream")
    client._client.stream = lambda *args, **kwargs: fake_context

    outputs = []
    async for msg in client.stream():
        outputs.append(msg)
        if len(outputs) == 2:
            break
    assert outputs[0]["result"]["val"] == 1
    assert outputs[1]["result"]["val"] == 2
