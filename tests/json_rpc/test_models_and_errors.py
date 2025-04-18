import pytest
from pydantic import ValidationError

from a2a.json_rpc import JSONRPCProtocol
from a2a.json_rpc.models import Request, Response
from a2a.json_rpc.json_rpc_error_codes import JsonRpcErrorCode
from a2a.json_rpc.a2a_error_codes import A2AErrorCode
from a2a.json_rpc.json_rpc_errors import (
    ParseError,
    InvalidRequestError,
    MethodNotFoundError,
    InvalidParamsError,
    InternalError,
)
from a2a.json_rpc.a2a_errors import (
    TaskNotFoundError,
    TaskNotCancelableError,
    PushNotificationsNotSupportedError,
    UnsupportedOperationError,
)

# ---- Model validation ----

def test_request_missing_method_raises_validation_error():
    with pytest.raises(ValidationError):
        Request(id=1)


def test_response_missing_id_raises_validation_error():
    with pytest.raises(ValidationError):
        Response(result="ok", error=None)


def test_models_round_trip():
    req_dict = {"jsonrpc": "2.0", "id": 5, "method": "echo", "params": {"a": 10}}
    req = Request.model_validate(req_dict)
    assert req.method == "echo"
    assert req.id == 5
    assert req.params == {"a": 10}
    assert req.model_dump(exclude_none=False) == req_dict

    resp_dict = {"jsonrpc": "2.0", "id": 5, "result": {"ok": True}, "error": None}
    resp = Response.model_validate(resp_dict)
    assert resp.result == {"ok": True}
    assert resp.error is None
    assert resp.model_dump(exclude_none=False) == resp_dict

# ---- Error codes & serialization ----

def test_parse_error_to_dict():
    err = ParseError("oops")
    d = err.to_dict()
    assert d["code"] == JsonRpcErrorCode.PARSE_ERROR
    assert d["message"] == "oops"
    assert "data" not in d


def test_invalid_request_error_with_data():
    err = InvalidRequestError("bad", data={"foo": "bar"})
    d = err.to_dict()
    assert d["code"] == JsonRpcErrorCode.INVALID_REQUEST
    assert d["data"] == {"foo": "bar"}


def test_method_not_found_error_defaults():
    err = MethodNotFoundError()
    d = err.to_dict()
    assert d["code"] == JsonRpcErrorCode.METHOD_NOT_FOUND


def test_internal_error_and_data():
    err = InternalError("fail", data=123)
    d = err.to_dict()
    assert d["code"] == JsonRpcErrorCode.INTERNAL_ERROR
    assert d["data"] == 123


def test_a2a_task_errors():
    e1 = TaskNotFoundError(data={"id": "t1"})
    d1 = e1.to_dict()
    assert d1["code"] == A2AErrorCode.TASK_NOT_FOUND
    assert d1["data"]["id"] == "t1"

    e2 = TaskNotCancelableError()
    assert e2.CODE == A2AErrorCode.TASK_NOT_CANCELABLE

# ---- JSONRPCProtocol helpers ----

def test_create_request_and_notification():
    proto = JSONRPCProtocol()
    r1 = proto.create_request("foo")
    r2 = proto.create_request("foo")
    assert isinstance(r1["id"], int)
    assert r2["id"] == r1["id"] + 1

    notif = proto.create_notification("foo", params={"x": 1})
    assert "id" not in notif


def test_protocol_batch_not_supported():
    proto = JSONRPCProtocol()
    # Passing a batch (list) should return an error response with INVALID_REQUEST
    resp = proto.handle_raw([{"jsonrpc": "2.0", "method": "foo"}])
    assert resp["error"]["code"] == InvalidRequestError().CODE
    assert resp["id"] is None
