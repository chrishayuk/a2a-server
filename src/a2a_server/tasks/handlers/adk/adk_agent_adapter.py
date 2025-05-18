#!/usr/bin/env python3
# a2a_server/tasks/handlers/adk/adk_agent_adapter.py
"""
ADK Agent Adapter
-----------------

Wraps any Google ADK ``Agent`` so it can be used by ``GoogleADKHandler``.
It provides the ``invoke`` (blocking) and ``stream`` (async streaming)
methods while transparently creating and re-using ADK session IDs so that
one A2A session maps to one persistent ADK session.

Key responsibilities
~~~~~~~~~~~~~~~~~~~~
* Ensure the correct ADK session is created or reused.
* Call the ADK ``Runner`` in the canonical positional form
  ``runner(user_id, session_id, …)``.
* Flatten final response parts without introducing extra new-lines.
* Gracefully handle events with ``None`` content or empty/invalid parts.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterable, Dict, List, Optional

from google.adk.agents import Agent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


class ADKAgentAdapter:
    """
    Adapter that wraps a Google ADK Agent into the interface expected by
    the A2A ``GoogleADKHandler`` (``invoke`` / ``stream``).

    Parameters
    ----------
    agent:
        The ADK ``Agent`` instance to wrap.
    user_id:
        Logical user identifier recorded in ADK sessions.
    """

    def __init__(self, agent: Agent, user_id: str = "a2a_user") -> None:
        self._agent = agent
        self._user_id = user_id

        # Expose the agent’s advertised content-type list (defaulting to text)
        self.SUPPORTED_CONTENT_TYPES: List[str] = getattr(
            agent, "SUPPORTED_CONTENT_TYPES", ["text/plain"]
        )

        # Prepare an in-memory Runner so every adapter instance is isolated
        self._runner = Runner(
            app_name=getattr(agent, "name", "adk_agent"),
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #
    def _get_or_create_session(self, session_id: Optional[str]) -> str:
        """
        Fetch an existing ADK session or create a new one.

        The `session_id` coming from A2A is reused so that subsequent calls
        map to the same ADK session; when `None`, ADK generates one.
        """
        session = self._runner.session_service.get_session(
            app_name=self._runner.app_name,
            user_id=self._user_id,
            session_id=session_id,
        )
        if session is None:
            session = self._runner.session_service.create_session(
                app_name=self._runner.app_name,
                user_id=self._user_id,
                state={},
                session_id=session_id,  # may be None → ADK generates one
            )
        return session.id

    # --------------------------------------------------------------------- #
    # Public synchronous interface                                          #
    # --------------------------------------------------------------------- #
    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        """
        Send ``query`` to the agent and block until the final response.

        Returns
        -------
        str
            The final response text, or an empty string when the agent
            produced no usable content.
        """
        adk_session_id = self._get_or_create_session(session_id)

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=query)],
        )

        events = list(
            self._runner.run(
                self._user_id,  # positional args mirror real Runner signature
                adk_session_id,
                new_message=content,
            )
        )

        # No events or unusable content → empty string
        if not events or not events[-1].content or not events[-1].content.parts:
            return ""

        # Concatenate part texts *without* new-lines (tests expect this)
        return "".join(
            part.text
            for part in events[-1].content.parts
            if getattr(part, "text", None)
        )

    # --------------------------------------------------------------------- #
    # Public asynchronous streaming interface                               #
    # --------------------------------------------------------------------- #
    async def stream(
        self, query: str, session_id: Optional[str] = None
    ) -> AsyncIterable[Dict[str, Any]]:
        """
        Yield incremental updates while the agent streams its response.

        Yields
        ------
        dict
            * ``{"is_task_complete": False, "updates": <str>}`` for
              intermediate chunks, and
            * ``{"is_task_complete": True,  "content": <str>}`` exactly once
              at completion.
        """
        adk_session_id = self._get_or_create_session(session_id)

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=query)],
        )

        # NB: Call ADK Runner *positionally* so test mocks can inspect args[1]
        async for event in self._runner.run_async(
            self._user_id,
            adk_session_id,
            new_message=content,
        ):
            # Safely extract text even when content/parts are missing
            parts = event.content.parts if event.content else []
            text = "".join(
                part.text for part in parts if getattr(part, "text", None)
            )

            if event.is_final_response():
                yield {"is_task_complete": True, "content": text}
            else:
                yield {"is_task_complete": False, "updates": text}
