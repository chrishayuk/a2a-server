# a2a_server/tasks/handlers/adk/__init__.py
"""
Google ADK (Agent Development Kit) handlers and adapters.
"""

# Initialize the __all__ list
__all__ = []

# Import GoogleADKHandler
try:
    from .google_adk_handler import GoogleADKHandler
    __all__.append("GoogleADKHandler")
except ImportError:
    pass

# Import ADKAgentAdapter
try:
    from .adk_agent_adapter import ADKAgentAdapter
    __all__.append("ADKAgentAdapter")
except ImportError:
    pass

# Import GoogleADKAgentProtocol
try:
    from .google_adk_protocol import GoogleADKAgentProtocol
    __all__.append("GoogleADKAgentProtocol")
except ImportError:
    pass

# Ensure we have at least some exports even if all imports fail
if not __all__:
    __all__ = []