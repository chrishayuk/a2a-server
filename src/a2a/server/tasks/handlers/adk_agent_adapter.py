#!/usr/bin/env python3
"""
ADK Agent Adapter

Wraps any Google ADK `Agent` into the required `invoke`/`stream` interface
for use with `GoogleADKHandler`, managing its own ADK session IDs.
"""
import asyncio
from typing import Any, AsyncIterable, Dict, Optional, List
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.genai import types

class ADKAgentAdapter:
    """
    Adapter that wraps a Google ADK Agent into the required interface,
    handling session creation and reuse so that each A2A session maps
    to a persistent ADK session.
    """
    def __init__(self, agent: Agent, user_id: str = "a2a_user") -> None:
        self._agent = agent
        self.SUPPORTED_CONTENT_TYPES: List[str] = getattr(
            agent, 'SUPPORTED_CONTENT_TYPES', ['text/plain']
        )
        self._user_id = user_id
        # Initialize Runner for sync and async calls
        self._runner = Runner(
            app_name=getattr(agent, 'name', 'adk_agent'),
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    def _get_or_create_session(self, session_id: Optional[str]) -> str:
        # Try to fetch existing session
        sess = self._runner.session_service.get_session(
            app_name=self._runner.app_name,
            user_id=self._user_id,
            session_id=session_id
        )
        if sess is None:
            sess = self._runner.session_service.create_session(
                app_name=self._runner.app_name,
                user_id=self._user_id,
                state={},
                session_id=session_id
            )
        return sess.id

    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        # Ensure we have a valid ADK session
        adk_session = self._get_or_create_session(session_id)
        # Build content for ADK agent
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=query)]
        )
        # Run synchronously
        events = list(
            self._runner.run(
                user_id=self._user_id,
                session_id=adk_session,
                new_message=content
            )
        )
        # Extract final response text
        if not events or not events[-1].content or not events[-1].content.parts:
            return ""
        return "\n".join(
            p.text for p in events[-1].content.parts if getattr(p, 'text', None)
        )

    async def stream(
        self, query: str, session_id: Optional[str] = None
    ) -> AsyncIterable[Dict[str, Any]]:
        # Ensure persistent session
        adk_session = self._get_or_create_session(session_id)
        # Build content
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=query)]
        )
        # Yield streaming updates
        async for event in self._runner.run_async(
            user_id=self._user_id,
            session_id=adk_session,
            new_message=content
        ):
            text = "".join(
                p.text for p in event.content.parts if getattr(p, 'text', None)
            )
            if not event.is_final_response():
                yield {"is_task_complete": False, "updates": text}
            else:
                yield {"is_task_complete": True, "content": text}
