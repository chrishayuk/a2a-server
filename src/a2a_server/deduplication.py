# a2a_server/deduplication.py - Simplified deduplication without temp IDs

import hashlib
import logging
import time
import json
from typing import Optional, Any

logger = logging.getLogger(__name__)

class SessionDeduplicator:
    """Session-based deduplication using the actual SessionManager provider."""
    
    def __init__(self, window_seconds: float = 3.0):
        self.window_seconds = window_seconds
    
    def _extract_message_text(self, message) -> str:
        """Extract text content from message."""
        try:
            if hasattr(message, 'parts') and message.parts:
                text_parts = []
                for part in message.parts:
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text.strip())
                return ' '.join(text_parts)
            elif isinstance(message, dict) and message.get('parts'):
                text_parts = []
                for part in message['parts']:
                    if isinstance(part, dict) and part.get('text'):
                        text_parts.append(part['text'].strip())
                return ' '.join(text_parts)
            return str(message)[:200]
        except Exception:
            return str(message)[:50] if message else ""
    
    def _create_dedup_key(self, session_id: str, message, handler: str) -> str:
        """Create deduplication key."""
        message_text = self._extract_message_text(message)
        normalized_text = ' '.join(message_text.split())
        content = f"{session_id}:{handler}:{normalized_text}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    async def check_duplicate(self, task_manager, session_id: str, message, handler: str) -> Optional[str]:
        """
        Check if this is a duplicate request.
        Returns existing task ID if duplicate found, None if new request.
        """
        session_manager = task_manager.session_manager
        
        if not session_manager:
            logger.warning("⚠️ No session manager available for deduplication")
            return None
        
        dedup_key = self._create_dedup_key(session_id, message, handler)
        storage_key = f"dedup:{dedup_key}"
        
        logger.info(f"🔍 Dedup check: key={dedup_key}, session={session_id[:8]}, handler={handler}")
        
        try:
            session_ctx_mgr = session_manager.session_factory()
            
            async with session_ctx_mgr as session:
                existing_raw = await session.get(storage_key)
                
                if existing_raw:
                    try:
                        existing_data = json.loads(existing_raw)
                        stored_time = existing_data.get('timestamp', 0)
                        stored_task_id = existing_data.get('task_id')
                        time_diff = time.time() - stored_time
                        
                        if time_diff < self.window_seconds and stored_task_id:
                            logger.info(f"🔄 Duplicate found: {stored_task_id} ({time_diff:.1f}s ago)")
                            return stored_task_id
                        else:
                            logger.debug(f"Entry expired: {time_diff:.1f}s > {self.window_seconds}s")
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in dedup entry: {existing_raw}")
                
                return None
                
        except Exception as e:
            logger.warning(f"❌ Dedup check failed: {e}")
            return None
    
    async def record_task(self, task_manager, session_id: str, message, handler: str, task_id: str) -> bool:
        """
        Record a task for future deduplication.
        Returns True if recorded successfully, False otherwise.
        """
        session_manager = task_manager.session_manager
        
        if not session_manager:
            return False
        
        dedup_key = self._create_dedup_key(session_id, message, handler)
        storage_key = f"dedup:{dedup_key}"
        
        try:
            session_ctx_mgr = session_manager.session_factory()
            
            async with session_ctx_mgr as session:
                new_data = {
                    'task_id': task_id,
                    'timestamp': time.time(),
                    'handler': handler,
                    'session_id': session_id
                }
                
                ttl_seconds = int(self.window_seconds * 2)
                await session.setex(storage_key, ttl_seconds, json.dumps(new_data))
                
                logger.info(f"✅ Recorded dedup entry: {storage_key} -> {task_id} (TTL: {ttl_seconds}s)")
                return True
                
        except Exception as e:
            logger.warning(f"❌ Failed to record dedup entry: {e}")
            return False

    def get_stats(self) -> dict:
        """Get deduplication statistics."""
        return {
            "window_seconds": self.window_seconds,
            "status": "active",
            "storage_method": "session_manager_provider"
        }

# Global deduplicator instance
deduplicator = SessionDeduplicator(window_seconds=3.0)