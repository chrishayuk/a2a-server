# a2a_server/__init__.py
"""
A2A-server top-level package.

▪ Exposes `create_app` so callers can build a FastAPI instance with their own
  config.  
▪ Provides a **lazy** `get_app()` helper plus a `__getattr__` shim, so legacy
  code that does `from a2a_server import app` still works - but the app is only
  instantiated the first time it's actually accessed.

Importing the package no longer spins up a default FastAPI application, which
eliminates the double-TaskManager issue seen with `uv run a2a-server …`.
"""

from typing import TYPE_CHECKING

from a2a_server.app import create_app
from a2a_server.pubsub import EventBus
from a2a_server.tasks.task_manager import (
    TaskManager,
    TaskNotFound,
    InvalidTransition,
)

if TYPE_CHECKING:  # for IDEs / static checkers
    from fastapi import FastAPI

__all__ = [
    "create_app",
    "get_app",
    "TaskManager",
    "TaskNotFound",
    "InvalidTransition",
    "EventBus",
]

# ---------------------------------------------------------------------------
# Lazy singleton - created on first access, not at import-time
# ---------------------------------------------------------------------------

_app_instance = None


def get_app(*args, **kwargs):  # noqa: D401
    """Return a singleton FastAPI app, creating it on first call.

    Prefer calling :func:`create_app` directly in new code; this helper exists
    mainly for frameworks that expect an ASGI `app` attribute.
    """
    global _app_instance  # pylint: disable=global-statement
    if _app_instance is None:
        _app_instance = create_app(*args, **kwargs)
    return _app_instance


def __getattr__(name):  # pragma: no cover
    """Lazy attribute hook so ``from a2a_server import app`` still works."""
    if name == "app":
        return get_app()
    raise AttributeError(name)
