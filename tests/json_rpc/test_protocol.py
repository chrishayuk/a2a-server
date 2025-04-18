import pytest
from pydantic import ValidationError
import json

from a2a.json_rpc import JSONRPCProtocol
from a2a.json_rpc.json_rpc_errors import ParseError, MethodNotFoundError, InternalError
from a2a.json_rpc.models import Request, Response


def test_request_model_valid():
    req = Request(method="foo", id=1, params={"x": 1})
    assert req.jsonrpc == "2.0"
    assert req.method == "foo"
    assert req.params == {"x": 1}


def test_request_model_invalid_missing_method():
    with pytest.raises(ValidationError):
        # Missing required 'method' argument should raise Pydantic ValidationError
        Request(id=1)


def test_response_model_valid():
    resp = Response(id=1, result={"ok": True}, error=None)
    assert resp.jsonrpc == "2.0"
    assert resp.result == {"ok": True}
    assert resp.error is None


def test_protocol_echo():
    proto = JSONRPCProtocol()

    @proto.method("echo")
    def echo_handler(_method, params):
        return params

    raw_req = {"jsonrpc": "2.0", "id": 1, "method": "echo", "params": {"hello": "world"}}
    resp = proto.handle_raw(raw_req)

    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp.get("result") == {"hello": "world"}
    assert resp.get("error") is None


def test_protocol_notification():
    proto = JSONRPCProtocol()
    calls = []

    @proto.method("notify")
    def notify_handler(_method, params):
        calls.append(params)
        return "ignored"

    notif = {"jsonrpc": "2.0", "method": "notify", "params": 123}
    resp = proto.handle_raw(notif)

    assert calls == [123]
    assert resp is None


def test_method_not_found():
    proto = JSONRPCProtocol()
    raw_req = {"jsonrpc": "2.0", "id": 2, "method": "unknown"}
    resp = proto.handle_raw(raw_req)

    assert resp["error"]["code"] == MethodNotFoundError().CODE
    assert resp.get("id") == 2


def test_parse_error():
    proto = JSONRPCProtocol()
    # malformed JSON ⇒ parse error
    resp = proto.handle_raw(b'{"jsonrpc":"2.0",')

    assert resp["error"]["code"] == ParseError().CODE
    assert resp.get("id") is None


def test_internal_error():
    proto = JSONRPCProtocol()

    @proto.method("boom")
    def boom_handler(_method, params):
        raise RuntimeError("oops")

    raw_req = {"jsonrpc": "2.0", "id": 3, "method": "boom"}
    resp = proto.handle_raw(raw_req)

    assert resp["error"]["code"] == InternalError().CODE
    assert resp.get("id") == 3
