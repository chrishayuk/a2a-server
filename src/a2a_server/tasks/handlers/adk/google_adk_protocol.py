# File: a2a_server/tasks/handlers/adk/google_adk_protocol.py
from typing import AsyncIterable, Dict, Any, Optional, List, Protocol

class GoogleADKAgentProtocol(Protocol):
    """Protocol defining required interface for Google ADK agents."""

    SUPPORTED_CONTENT_TYPES: List[str]

    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        pass

    async def stream(self, query: str, session_id: Optional[str] = None) -> AsyncIterable[Dict[str, Any]]:
        pass