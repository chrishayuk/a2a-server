"""
A2A server module.

This module provides a flexible RPC server for Agent-to-Agent communication
with support for multiple transports (HTTP, WebSocket, SSE, stdio).
"""

from a2a.server.app import create_app
from a2a.server.tasks.task_manager import TaskManager, TaskNotFound, InvalidTransition
from a2a.server.pubsub import EventBus

# Expose a preconfigured FastAPI app instance
app = create_app()

__all__ = [
    'create_app',
    'app',
    'TaskManager',
    'TaskNotFound',
    'InvalidTransition',
    'EventBus',
]
