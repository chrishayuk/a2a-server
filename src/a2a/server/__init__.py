# File: src/a2a/server/__init__.py
"""
Expose the FastAPI application for ASGI transports and tests.
"""
from a2a.server.app import app, create_app

__all__ = ["app", "create_app"]