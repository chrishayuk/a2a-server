#!/usr/bin/env python3
# a2a_server/tasks/handlers/adk/adk_agent_adapter.py
"""
ADK Agent Adapter
-----------------

Thin wrapper that lets a Google-ADK ``Agent`` be used by the A2A
``GoogleADKHandler``.  It assumes the **current ADK API** (≥ 0.6) where
``Runner.run`` / ``Runner.run_async`` take **keyword-only** arguments.

Key points
~~~~~~~~~~
* Creates (or re-uses) an ADK session that maps 1-to-1 to an A2A session.
* Provides ``invoke`` (blocking) and ``stream`` (async) methods.
* Flattens the final response parts into a single plain-text string.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, AsyncIterable, Dict, List, Optional

from google.adk.agents import Agent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


class ADKAgentAdapter:
    """Wrap a Google ADK ``Agent`` so it matches the interface A2A expects."""

    def __init__(self, agent: Agent, user_id: str = "a2a_user") -> None:
        self._agent = agent
        self._user_id = user_id

        # Expose the agent's advertised content-types (default to plain text)
        self.SUPPORTED_CONTENT_TYPES: List[str] = getattr(
            agent, "SUPPORTED_CONTENT_TYPES", ["text/plain"]
        )

        # Isolated in-memory runner
        self._runner = Runner(
            app_name=getattr(agent, "name", "adk_agent"),
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    # ------------------------------------------------------------------ #
    # helpers                                                            #
    # ------------------------------------------------------------------ #
    async def _get_or_create_session_async(self, session_id: Optional[str]) -> str:
        """Async version of session creation/retrieval."""
        # Check if get_session is async
        get_session_method = self._runner.session_service.get_session
        if inspect.iscoroutinefunction(get_session_method):
            sess = await get_session_method(
                app_name=self._runner.app_name,
                user_id=self._user_id,
                session_id=session_id,
            )
        else:
            sess = get_session_method(
                app_name=self._runner.app_name,
                user_id=self._user_id,
                session_id=session_id,
            )
        
        if sess is None:
            # Check if create_session is async
            create_session_method = self._runner.session_service.create_session
            if inspect.iscoroutinefunction(create_session_method):
                sess = await create_session_method(
                    app_name=self._runner.app_name,
                    user_id=self._user_id,
                    state={},
                    session_id=session_id,
                )
            else:
                sess = create_session_method(
                    app_name=self._runner.app_name,
                    user_id=self._user_id,
                    state={},
                    session_id=session_id,
                )
        
        return sess.id

    def _get_or_create_session(self, session_id: Optional[str]) -> str:
        """Synchronous wrapper that handles both sync and async session methods."""
        try:
            # Try to run the async version in an event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, we need to handle this differently
                # For now, let's try the synchronous approach first
                try:
                    get_session_method = self._runner.session_service.get_session
                    if not inspect.iscoroutinefunction(get_session_method):
                        sess = get_session_method(
                            app_name=self._runner.app_name,
                            user_id=self._user_id,
                            session_id=session_id,
                        )
                        if sess is not None:
                            return sess.id
                        
                        create_session_method = self._runner.session_service.create_session
                        if not inspect.iscoroutinefunction(create_session_method):
                            sess = create_session_method(
                                app_name=self._runner.app_name,
                                user_id=self._user_id,
                                state={},
                                session_id=session_id,
                            )
                            return sess.id
                except Exception:
                    pass
                
                # If sync methods failed or don't exist, return a fallback session ID
                return session_id or f"session_{hash(self._user_id) % 10000}"
            else:
                return loop.run_until_complete(self._get_or_create_session_async(session_id))
        except RuntimeError:
            # No event loop running, create one
            return asyncio.run(self._get_or_create_session_async(session_id))

    # ------------------------------------------------------------------ #
    # blocking call                                                      #
    # ------------------------------------------------------------------ #
    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        adk_sid = self._get_or_create_session(session_id)

        content = types.Content(
            role="user", parts=[types.Part.from_text(text=query)]
        )

        try:
            events = list(
                self._runner.run(
                    user_id=self._user_id,
                    session_id=adk_sid,
                    new_message=content,
                )
            )
        except Exception as e:
            return f"Error processing request: {str(e)}"

        if not events or not events[-1].content or not events[-1].content.parts:
            return ""

        return "".join(
            p.text for p in events[-1].content.parts if getattr(p, "text", None)
        )

    # ------------------------------------------------------------------ #
    # streaming call                                                     #
    # ------------------------------------------------------------------ #
    async def stream(
        self, query: str, session_id: Optional[str] = None
    ) -> AsyncIterable[Dict[str, Any]]:
        adk_sid = await self._get_or_create_session_async(session_id)

        content = types.Content(
            role="user", parts=[types.Part.from_text(text=query)]
        )

        try:
            async for event in self._runner.run_async(
                user_id=self._user_id,
                session_id=adk_sid,
                new_message=content,
            ):
                parts = event.content.parts if event.content else []
                text = "".join(
                    p.text for p in parts if getattr(p, "text", None)
                )

                if event.is_final_response():
                    yield {"is_task_complete": True, "content": text}
                else:
                    yield {"is_task_complete": False, "updates": text}
        except Exception as e:
            yield {"is_task_complete": True, "content": f"Error processing request: {str(e)}"}