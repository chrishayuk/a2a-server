import pytest
import httpx
from a2a.client.transport.http import JSONRPCHTTPClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError

@pytest.mark.asyncio
async def test_call_success(monkeypatch):
    # Mock HTTP transport to return a successful JSON-RPC response
    def handler(request: httpx.Request):
        return httpx.Response(
            status_code=200,
            json={"jsonrpc": "2.0", "result": {"ok": True}, "id": None},
        )

    mock_transport = httpx.MockTransport(handler)
    client = JSONRPCHTTPClient("http://test")
    client._client = httpx.AsyncClient(transport=mock_transport)

    result = await client.call("foo", {"a": 1})
    assert result == {"ok": True}

@pytest.mark.asyncio
async def test_call_error(monkeypatch):
    # Mock HTTP transport to return a JSON-RPC error
    def handler(request: httpx.Request):
        return httpx.Response(
            status_code=200,
            json={"jsonrpc": "2.0", "error": {"code": -32001, "message": "Not found"}, "id": None},
        )

    mock_transport = httpx.MockTransport(handler)
    client = JSONRPCHTTPClient("http://test")
    client._client = httpx.AsyncClient(transport=mock_transport)

    with pytest.raises(JSONRPCError) as excinfo:
        await client.call("foo", {})
    assert "Not found" in str(excinfo.value)

@pytest.mark.asyncio
async def test_notify(monkeypatch):
    # Mock HTTP transport to ensure notify does not raise
    called = False
    def handler(request: httpx.Request):
        nonlocal called
        called = True
        return httpx.Response(status_code=204)

    mock_transport = httpx.MockTransport(handler)
    client = JSONRPCHTTPClient("http://test")
    client._client = httpx.AsyncClient(transport=mock_transport)

    await client.notify("foo", {"x": 2})
    assert called


def test_stream_raises_not_implemented():
    client = JSONRPCHTTPClient("http://test")
    with pytest.raises(NotImplementedError):
        _ = client.stream()
