#!/usr/bin/env python3
# a2a_server/tasks/handlers/adk/adk_agent_adapter.py
"""
Simple Working ADK Agent Adapter
--------------------------------

This version prioritizes working functionality over complex session management.
It handles ADK sessions simply and gracefully handles errors.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import uuid
from typing import Any, AsyncIterable, Dict, List, Optional

from google.adk.agents import Agent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

logger = logging.getLogger(__name__)


class ADKAgentAdapter:
    """Simple, working wrapper for Google ADK Agent."""

    def __init__(self, agent: Agent, user_id: str = "a2a_user") -> None:
        self._agent = agent
        self._user_id = user_id

        # Expose the agent's advertised content-types (default to plain text)
        self.SUPPORTED_CONTENT_TYPES: List[str] = getattr(
            agent, "SUPPORTED_CONTENT_TYPES", ["text/plain"]
        )

        # Create isolated runner
        self._runner = Runner(
            app_name=getattr(agent, "name", "adk_agent"),
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )
        
        logger.debug(f"🔧 ADK Adapter initialized for agent: {getattr(agent, 'name', 'unknown')}")

    def _get_or_create_session_original(self, session_id: Optional[str]) -> str:
        """Original working session handling method."""
        try:
            # Try to run the async version in an event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, use synchronous approach
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
                
                # If sync methods failed, use fallback session ID
                fallback_id = session_id or f"session_{hash(self._user_id) % 10000}"
                logger.debug(f"🔧 Using fallback session: {fallback_id}")
                return fallback_id
            else:
                return loop.run_until_complete(self._get_or_create_session_async_original(session_id))
        except RuntimeError:
            # No event loop running, create one
            return asyncio.run(self._get_or_create_session_async_original(session_id))

    async def _get_or_create_session_async_original(self, session_id: Optional[str]) -> str:
        """Original async session creation."""
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

    def _extract_text_from_parts(self, parts: List[Any]) -> str:
        """Extract and join text from content parts."""
        text_parts = []
        for part in parts:
            if hasattr(part, 'text') and part.text:
                text_parts.append(part.text)
        
        result = "".join(text_parts).strip()
        
        # Basic cleaning
        if result:
            import re
            result = re.sub(r'\s+', ' ', result)
            result = re.sub(r'\.{2,}', '.', result)
        
        return result

    def _validate_response(self, text: str) -> str:
        """Validate and clean response text."""
        if not text or not text.strip():
            return "I apologize, but my response was empty. Please try again."
        
        # Check for malformed responses
        malformed_patterns = ["I'm You are", "You asked:"]
        for pattern in malformed_patterns:
            if pattern in text:
                logger.warning(f"⚠️ Detected malformed response pattern: {pattern}")
                return "I apologize, but I encountered an issue generating a response. Please try again."
        
        return text.strip()

    def _run_adk_simple(self, query: str, session_id: Optional[str] = None) -> str:
        """
        Run ADK using the ORIGINAL working session handling in isolated thread.
        """
        result_container = {}
        exception_container = {}
        
        def isolated_runner():
            """Run ADK in isolation using the original working approach."""
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Use the ORIGINAL session handling that was working
                    adk_sid = self._get_or_create_session_original(session_id)
                    logger.debug(f"🔧 Using ADK session: {adk_sid}")

                    content = types.Content(
                        role="user", parts=[types.Part.from_text(text=query)]
                    )

                    logger.debug(f"🔧 Running ADK agent...")
                    
                    # Use the original working call
                    events = list(
                        self._runner.run(
                            user_id=self._user_id,
                            session_id=adk_sid,
                            new_message=content,
                        )
                    )
                    
                    logger.debug(f"✅ ADK run completed with {len(events)} events")
                    
                    # Process results
                    if not events:
                        result_container['result'] = "I apologize, but I didn't receive a response. Please try again."
                        return
                    
                    final_event = events[-1]
                    if not final_event.content or not final_event.content.parts:
                        result_container['result'] = "I apologize, but I couldn't generate a response. Please try again."
                        return

                    # Extract text
                    text = self._extract_text_from_parts(final_event.content.parts)
                    
                    if not text:
                        result_container['result'] = "I apologize, but I couldn't generate a text response. Please try again."
                        return
                    
                    # Validate and store result
                    validated_result = self._validate_response(text)
                    result_container['result'] = validated_result
                    
                finally:
                    loop.close()
                    
            except Exception as e:
                exception_container['exception'] = e
                logger.error(f"❌ ADK isolated runner error: {e}")
        
        # Run in isolated thread
        thread = threading.Thread(target=isolated_runner, daemon=True)
        thread.start()
        thread.join(timeout=240)  # 4 minute timeout
        
        # Check results
        if thread.is_alive():
            logger.error("❌ ADK runner timed out")
            return "I apologize, but the request timed out. Please try again."
        
        if 'exception' in exception_container:
            error = exception_container['exception']
            logger.error(f"❌ ADK runner failed: {error}")
            return f"I apologize, but I encountered an error: {str(error)}"
        
        if 'result' not in result_container:
            logger.error("❌ ADK runner completed but no result")
            return "I apologize, but I couldn't generate a response. Please try again."
        
        return result_container['result']

    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        """
        Invoke the ADK agent with simple, reliable handling.
        """
        logger.info(f"🔧 ADK invoke called with query: {query[:100]}...")
        
        try:
            # Use simple isolated approach
            result = self._run_adk_simple(query, session_id)
            
            logger.debug(f"✅ ADK invoke successful: {len(result)} chars")
            return result
            
        except Exception as e:
            error_msg = f"Error processing request with ADK agent: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return f"I apologize, but I encountered an error: {str(e)}"

    async def stream(
        self, query: str, session_id: Optional[str] = None
    ) -> AsyncIterable[Dict[str, Any]]:
        """
        Stream responses using simple blocking invoke.
        """
        logger.info(f"🔧 ADK stream called with query: {query[:100]}...")
        
        try:
            # Use the blocking invoke in a thread
            result = await asyncio.to_thread(self.invoke, query, session_id)
            
            logger.debug(f"✅ ADK stream completed: {len(result)} chars")
            yield {"is_task_complete": True, "content": result}
                    
        except Exception as e:
            error_msg = f"Error during ADK streaming: {str(e)}"
            logger.error(f"❌ {error_msg}")
            yield {"is_task_complete": True, "content": f"I apologize, but I encountered an error: {str(e)}"}

    @property
    def name(self) -> str:
        """Get agent name."""
        return getattr(self._agent, 'name', 'adk_agent')
    
    @property 
    def model(self) -> str:
        """Get agent model."""
        return getattr(self._agent, 'model', 'unknown')


# Export class
__all__ = ["ADKAgentAdapter"]