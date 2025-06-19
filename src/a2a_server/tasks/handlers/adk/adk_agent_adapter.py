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
* FIXED: Better error handling and response validation
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, AsyncIterable, Dict, List, Optional

from google.adk.agents import Agent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

logger = logging.getLogger(__name__)


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
        
        logger.info(f"🔧 ADK Adapter initialized for agent: {getattr(agent, 'name', 'unknown')}")

    # ------------------------------------------------------------------ #
    # helpers                                                            #
    # ------------------------------------------------------------------ #
    async def _get_or_create_session_async(self, session_id: Optional[str]) -> str:
        """Async version of session creation/retrieval."""
        try:
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
            
            session_result = sess.id if sess else (session_id or "default_session")
            logger.debug(f"🔧 ADK session: {session_result}")
            return session_result
            
        except Exception as e:
            logger.warning(f"⚠️ Session creation failed: {e}")
            return session_id or "fallback_session"

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
                except Exception as e:
                    logger.debug(f"🔧 Sync session creation failed: {e}")
                
                # If sync methods failed or don't exist, return a fallback session ID
                fallback_id = session_id or f"session_{hash(self._user_id) % 10000}"
                logger.debug(f"🔧 Using fallback session: {fallback_id}")
                return fallback_id
            else:
                return loop.run_until_complete(self._get_or_create_session_async(session_id))
        except RuntimeError:
            # No event loop running, create one
            return asyncio.run(self._get_or_create_session_async(session_id))

    def _extract_text_from_parts(self, parts: List[Any]) -> str:
        """Extract and join text from content parts with validation."""
        text_parts = []
        for part in parts:
            if hasattr(part, 'text') and part.text:
                text_parts.append(part.text)
        
        result = "".join(text_parts).strip()
        
        # Additional cleaning for common ADK formatting issues
        if result:
            # Remove any duplicate whitespace
            import re
            result = re.sub(r'\s+', ' ', result)
            # Remove any trailing periods that might be duplicated
            result = re.sub(r'\.{2,}', '.', result)
        
        return result

    def _validate_response(self, text: str) -> str:
        """Validate and clean response text."""
        if not text or not text.strip():
            return "I apologize, but my response was empty. Please try again."
        
        # Check for malformed responses (the patterns we've seen before)
        malformed_patterns = [
            "I'm You are",
            "You asked:",
            # Add other patterns if they emerge
        ]
        
        for pattern in malformed_patterns:
            if pattern in text:
                logger.warning(f"⚠️ Detected malformed response pattern: {pattern}")
                return "I apologize, but I encountered an issue generating a response. Please try again."
        
        return text.strip()

    # ------------------------------------------------------------------ #
    # blocking call                                                      #
    # ------------------------------------------------------------------ #
    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        logger.info(f"🔧 ADK invoke called with query: {query[:100]}...")
        
        try:
            adk_sid = self._get_or_create_session(session_id)
            logger.debug(f"🔧 Using ADK session: {adk_sid}")

            content = types.Content(
                role="user", parts=[types.Part.from_text(text=query)]
            )

            logger.debug(f"🔧 Running ADK agent...")
            events = list(
                self._runner.run(
                    user_id=self._user_id,
                    session_id=adk_sid,
                    new_message=content,
                )
            )
            
            logger.info(f"✅ ADK run completed with {len(events)} events")
            
            # FIXED: Better response validation and error handling
            if not events:
                logger.warning("⚠️ No events returned from ADK agent")
                return "I apologize, but I didn't receive a response. Please try again."
            
            final_event = events[-1]
            if not final_event.content or not final_event.content.parts:
                logger.warning("⚠️ Final event has no content or parts")
                return "I apologize, but I couldn't generate a response. Please try again."

            # Extract and validate text
            result = self._extract_text_from_parts(final_event.content.parts)
            
            if not result:
                logger.warning("⚠️ No text content found in response parts")
                return "I apologize, but I couldn't generate a text response. Please try again."
            
            # Validate and clean the response
            validated_result = self._validate_response(result)
            
            logger.info(f"✅ ADK invoke successful: {len(validated_result)} chars")
            return validated_result
            
        except Exception as e:
            error_msg = f"Error processing request with ADK agent: {str(e)}"
            logger.error(f"❌ {error_msg}")
            logger.exception("ADK invoke error:")
            return f"I apologize, but I encountered an error: {str(e)}"

    # ------------------------------------------------------------------ #
    # streaming call                                                     #
    # ------------------------------------------------------------------ #
    async def stream(
        self, query: str, session_id: Optional[str] = None
    ) -> AsyncIterable[Dict[str, Any]]:
        logger.info(f"🔧 ADK stream called with query: {query[:100]}...")
        
        try:
            adk_sid = await self._get_or_create_session_async(session_id)
            logger.debug(f"🔧 Using ADK session: {adk_sid}")

            content = types.Content(
                role="user", parts=[types.Part.from_text(text=query)]
            )

            logger.debug(f"🔧 Starting ADK async run...")
            
            async for event in self._runner.run_async(
                user_id=self._user_id,
                session_id=adk_sid,
                new_message=content,
            ):
                parts = event.content.parts if event.content else []
                text = self._extract_text_from_parts(parts)

                if event.is_final_response():
                    # Validate final response
                    validated_text = self._validate_response(text)
                    
                    logger.info(f"✅ ADK stream final response: {len(validated_text)} chars")
                    yield {"is_task_complete": True, "content": validated_text}
                else:
                    # For intermediate updates, just clean basic formatting
                    clean_text = text.strip() if text else ""
                    if clean_text:
                        yield {"is_task_complete": False, "updates": clean_text}
                    
        except Exception as e:
            error_msg = f"Error during ADK streaming: {str(e)}"
            logger.error(f"❌ {error_msg}")
            logger.exception("ADK stream error:")
            yield {"is_task_complete": True, "content": f"I apologize, but I encountered an error: {str(e)}"}