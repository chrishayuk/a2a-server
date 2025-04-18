# File: src/a2a/server/__init__.py
"""
A2A server module.

This module provides a flexible RPC server for Agent-to-Agent communication
with support for multiple transports (HTTP, WebSocket, SSE, stdio).
"""

from a2a.server.app import app, create_app
from a2a.server.tasks.task_manager import TaskManager, TaskNotFound, InvalidTransition
from a2a.server.pubsub import EventBus

__all__ = [
    'app',
    'create_app',
    'TaskManager',
    'TaskNotFound',
    'InvalidTransition',
    'EventBus',
]