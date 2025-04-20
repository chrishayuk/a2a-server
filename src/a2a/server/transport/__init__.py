# a2a/server/transport/__init__.py
"""
Transports for the A2A server.
"""
from a2a.server.transport.http import setup_http
from a2a.server.transport.ws import setup_ws
from a2a.server.transport.sse import setup_sse
from a2a.server.transport.stdio import handle_stdio_message

# Export transport setup functions
__all__ = ['setup_http', 'setup_ws', 'setup_sse', 'handle_stdio_message']