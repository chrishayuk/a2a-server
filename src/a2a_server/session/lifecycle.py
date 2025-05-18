#!/usr/bin/env python3
# a2a_server/session/lifecycle.py
"""
Session lifecycle management for A2A server.

Manages automatic cleanup of inactive sessions to prevent memory leaks
and ensure optimal performance in long-running applications.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Import session-related types
from a2a_server.tasks.handlers.adk.session_enabled_adk_handler import SessionAwareTaskHandler

logger = logging.getLogger(__name__)

class SessionLifecycleManager:
    """
    Manages the lifecycle of sessions including cleanup of inactive sessions.
    
    This manager periodically scans for sessions that haven't been active
    for a configurable period and removes them from both the handler's
    session map and the underlying session store.
    """
    
    def __init__(
        self, 
        task_manager,
        max_session_age: int = 24*60*60,  # 24 hours in seconds
        cleanup_interval: int = 60*60     # 1 hour in seconds
    ):
        """
        Initialize the session lifecycle manager.
        
        Args:
            task_manager: The TaskManager containing session-enabled handlers
            max_session_age: Maximum session age in seconds before cleanup (default: 24 hours)
            cleanup_interval: Interval between cleanup runs in seconds (default: 1 hour)
        """
        self.task_manager = task_manager
        self.max_session_age = max_session_age
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(
                "Session lifecycle manager started (max_age=%s, interval=%s)",
                self.max_session_age, 
                self.cleanup_interval
            )
    
    async def stop(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Session lifecycle manager stopped")
    
    async def _cleanup_loop(self) -> None:
        """Periodically clean up inactive sessions."""
        while True:
            try:
                await self._cleanup_inactive_sessions()
            except Exception as e:
                logger.exception("Error during session cleanup: %s", e)
            
            # Sleep until the next cleanup interval
            await asyncio.sleep(self.cleanup_interval)
    
    async def _cleanup_inactive_sessions(self) -> None:
        """Clean up sessions that haven't been active for too long."""
        cutoff_time = datetime.now() - timedelta(seconds=self.max_session_age)
        inactive_sessions = await self._find_inactive_sessions(cutoff_time)
        
        if inactive_sessions:
            logger.info("Cleaning up %d inactive sessions", len(inactive_sessions))
            for handler_name, session_id in inactive_sessions:
                try:
                    await self._remove_session(handler_name, session_id)
                except Exception as e:
                    logger.error("Error removing session %s from %s: %s", 
                                session_id, handler_name, e)
    
    async def _find_inactive_sessions(self, cutoff_time: datetime) -> List[Tuple[str, str]]:
        """
        Find sessions that haven't been active since cutoff_time.
        
        Returns a list of (handler_name, session_id) tuples for inactive sessions.
        """
        inactive_sessions = []
        
        # Get all handlers that support sessions
        session_handlers = self._get_session_handlers()
        for handler_name, handler in session_handlers.items():
            # Check each session in the handler's map
            for a2a_session_id, chuk_session_id in list(handler._session_map.items()):
                try:
                    # Get the session from the store
                    session_store = handler._conversation_manager._store
                    session = await session_store.get(chuk_session_id)
                    
                    # Check if the session exists and has last_updated
                    if session and hasattr(session, 'last_updated') and session.last_updated:
                        # Convert to datetime if needed
                        last_updated = session.last_updated
                        if isinstance(last_updated, str):
                            try:
                                last_updated = datetime.fromisoformat(last_updated)
                            except ValueError:
                                continue
                        
                        # Check if the session is inactive
                        if last_updated < cutoff_time:
                            inactive_sessions.append((handler_name, a2a_session_id))
                except Exception as e:
                    logger.error("Error checking session activity for %s: %s", 
                                a2a_session_id, e)
        
        return inactive_sessions
    
    async def _remove_session(self, handler_name: str, session_id: str) -> None:
        """
        Remove a session from both the handler and the session store.
        
        Args:
            handler_name: Name of the handler containing the session
            session_id: A2A session ID to remove
        """
        handlers = self._get_session_handlers()
        if handler_name in handlers:
            handler = handlers[handler_name]
            
            # Get the chuk session ID from the mapping
            chuk_session_id = handler._session_map.get(session_id)
            if chuk_session_id:
                # Remove from handler's session map
                handler._session_map.pop(session_id, None)
                
                # Remove from session store
                try:
                    session_store = handler._conversation_manager._store
                    await session_store.delete(chuk_session_id)
                    logger.info("Removed session %s from handler %s", 
                               session_id, handler_name)
                except Exception as e:
                    logger.error("Error deleting session %s from store: %s", 
                                chuk_session_id, e)
    
    def _get_session_handlers(self) -> Dict[str, SessionAwareTaskHandler]:
        """Get all handlers that support sessions."""
        result = {}
        
        for handler_name in self.task_manager.get_handlers():
            handler = self.task_manager._handlers.get(handler_name)
            if handler and isinstance(handler, SessionAwareTaskHandler):
                result[handler_name] = handler
        
        return result
        
    async def get_session_stats(self) -> Dict:
        """
        Get statistics about current sessions.
        
        Returns a dictionary with session counts by handler and total.
        """
        stats = {
            "total_sessions": 0,
            "by_handler": {},
            "oldest_session": None,
            "newest_session": None
        }
        
        session_handlers = self._get_session_handlers()
        oldest_time = None
        newest_time = None
        
        for handler_name, handler in session_handlers.items():
            session_count = len(handler._session_map)
            stats["by_handler"][handler_name] = session_count
            stats["total_sessions"] += session_count
            
            # Check session timestamps if available
            for a2a_session_id, chuk_session_id in handler._session_map.items():
                try:
                    session_store = handler._conversation_manager._store
                    session = await session_store.get(chuk_session_id)
                    
                    if session and hasattr(session, 'created_at') and session.created_at:
                        created_at = session.created_at
                        if isinstance(created_at, str):
                            try:
                                created_at = datetime.fromisoformat(created_at)
                            except ValueError:
                                continue
                        
                        if oldest_time is None or created_at < oldest_time:
                            oldest_time = created_at
                            stats["oldest_session"] = {
                                "handler": handler_name,
                                "session_id": a2a_session_id,
                                "created_at": created_at.isoformat()
                            }
                        
                        if newest_time is None or created_at > newest_time:
                            newest_time = created_at
                            stats["newest_session"] = {
                                "handler": handler_name,
                                "session_id": a2a_session_id,
                                "created_at": created_at.isoformat()
                            }
                except Exception:
                    pass
        
        return stats