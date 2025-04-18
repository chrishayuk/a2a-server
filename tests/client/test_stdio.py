import pytest
import sys
import json
from a2a.client.transport.stdio import JSONRPCStdioTransport
from a2a.json_rpc.json_rpc_errors import JSONRPCError

@pytest.mark.asyncio
async def test_stdio_call_and_notify(monkeypatch, capsys):
    # Prepare a response line for stdin.readline
    response = {"jsonrpc": "2.0", "result": 100, "id": None}
    monkeypatch.setattr(sys, 'stdin', type('S', (), {'readline': lambda self: json.dumps(response) + '\n'})())

    transport = JSONRPCStdioTransport()
    # Test call prints request and returns result
    result = await transport.call('foo', {'a': 1})
    captured = capsys.readouterr()
    out = captured.out.strip()
    req = json.loads(out)
    assert req['method'] == 'foo'
    assert result == 100

    # Prepare an error response
    error = {"jsonrpc": "2.0", "error": {"code": -32004, "message": "Op not supported"}, "id": None}
    monkeypatch.setattr(sys, 'stdin', type('S', (), {'readline': lambda self: json.dumps(error) + '\n'})())
    with pytest.raises(JSONRPCError):
        await transport.call('foo', {})

@pytest.mark.asyncio
async def test_stdio_stream(monkeypatch):
    # Simulate multiple lines in stdin
    lines = [json.dumps({"jsonrpc": "2.0", "result": 1}), '\n', '']
    iterator = iter(lines)
    monkeypatch.setattr(sys, 'stdin', type('S', (), {'readline': lambda self: next(iterator)})())

    transport = JSONRPCStdioTransport()
    outputs = []
    async for msg in transport.stream():
        outputs.append(msg)
    assert outputs[0]["result"] == 1
