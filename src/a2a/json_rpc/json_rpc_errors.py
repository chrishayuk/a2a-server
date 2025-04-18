# a2a/json_rpc/json_rpc_errors.py
"""
Standard JSON-RPC 2.0 error definitions.
"""
from typing import Any, Dict

from a2a.json_rpc.json_rpc_error_codes import JsonRpcErrorCode


class JSONRPCError(Exception):
    """Base for all JSON-RPC errors."""
    CODE: JsonRpcErrorCode

    def __init__(self, message: str | None = None, *, data: Any | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message: str = message or self.__class__.__name__
        self.data: Any | None = data

    def to_dict(self) -> Dict[str, Any]:
        err: Dict[str, Any] = {"code": int(self.CODE), "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


class ParseError(JSONRPCError):
    """Invalid JSON was received by the server."""
    CODE = JsonRpcErrorCode.PARSE_ERROR


class InvalidRequestError(JSONRPCError):
    """The JSON sent is not a valid Request object."""
    CODE = JsonRpcErrorCode.INVALID_REQUEST


class MethodNotFoundError(JSONRPCError):
    """The method does not exist / is not available."""
    CODE = JsonRpcErrorCode.METHOD_NOT_FOUND


class InvalidParamsError(JSONRPCError):
    """Invalid method parameter(s)."""
    CODE = JsonRpcErrorCode.INVALID_PARAMS


class InternalError(JSONRPCError):
    """Internal JSON-RPC error."""
    CODE = JsonRpcErrorCode.INTERNAL_ERROR
