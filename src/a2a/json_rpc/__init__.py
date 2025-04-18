# a2a/json_rpc/__init__.py
"""
Top-level API for A2A JSON-RPC.
Exports the protocol dispatcher, standard JSON-RPC errors, and A2A-specific errors.
"""

from a2a.json_rpc.protocol import JSONRPCProtocol

# Standard JSON-RPC errors
from a2a.json_rpc.json_rpc_errors import (
    JSONRPCError as BaseJSONRPCError,
    ParseError,
    InvalidRequestError,
    MethodNotFoundError,
    InvalidParamsError,
    InternalError,
)

# A2A-specific errors
from a2a.json_rpc.a2a_errors import (
    TaskNotFoundError,
    TaskNotCancelableError,
    PushNotificationsNotSupportedError,
    UnsupportedOperationError,
)

__all__ = [
    "JSONRPCProtocol",

    # Standard JSON-RPC
    "BaseJSONRPCError",
    "ParseError",
    "InvalidRequestError",
    "MethodNotFoundError",
    "InvalidParamsError",
    "InternalError",

    # A2A-specific
    "TaskNotFoundError",
    "TaskNotCancelableError",
    "PushNotificationsNotSupportedError",
    "UnsupportedOperationError",
]
