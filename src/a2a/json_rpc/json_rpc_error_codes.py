
# a2a/json_rpc/json_rpc_error_codes.py
from enum import IntEnum

class JsonRpcErrorCode(IntEnum):
    """Standard JSON-RPC 2.0"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
