# a2a/json_rpc/a2a_errors.py
"""
A2A-specific error definitions.
"""
from typing import Any, Dict

from a2a.json_rpc.a2a_error_codes import A2AErrorCode
from a2a.json_rpc.json_rpc_errors import JSONRPCError


class TaskNotFoundError(JSONRPCError):
    """A requested task was not found."""
    CODE = A2AErrorCode.TASK_NOT_FOUND


class TaskNotCancelableError(JSONRPCError):
    """A requested task cannot be canceled."""
    CODE = A2AErrorCode.TASK_NOT_CANCELABLE


class PushNotificationsNotSupportedError(JSONRPCError):
    """Push notifications are not supported by this agent."""
    CODE = A2AErrorCode.PUSH_NOTIFICATIONS_NOT_SUPPORTED


class UnsupportedOperationError(JSONRPCError):
    """An operation is not supported by this agent."""
    CODE = A2AErrorCode.UNSUPPORTED_OPERATION
