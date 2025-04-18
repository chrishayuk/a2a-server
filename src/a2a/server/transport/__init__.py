# a2a/server/transport/__init__.py
from a2a.server.transport.http import setup_http
from a2a.server.transport.ws import setup_ws
from a2a.server.transport.sse import setup_sse

# register all
__all__ = ['setup_http', 'setup_ws', 'setup_sse']