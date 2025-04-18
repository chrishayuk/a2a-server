# a2a/json_rpc/a2a_error_codes.py
from enum import IntEnum

class A2AErrorCode(IntEnum):
    """A2A-specific error codes."""
    # A2A-specific
    TASK_NOT_FOUND = -32001
    TASK_NOT_CANCELABLE = -32002
    PUSH_NOTIFICATIONS_NOT_SUPPORTED = -32003
    UNSUPPORTED_OPERATION = -32004
