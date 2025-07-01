# a2a_server/deduplication.py - Complete fix with session normalization

import hashlib
import logging
import time
import json
from typing import Optional, Any

logger = logging.getLogger(__name__)

class SessionDeduplicator:
    """Session-based deduplication with session ID normalization."""
    
    def __init__(self, window_seconds: float = 3.0):
        self.window_seconds = window_seconds
    
    def _extract_message_text(self, message) -> str:
        """Extract text content from message with enhanced debugging."""
        try:
            # DEBUG: Log what we're trying to extract from
            logger.debug(f"🔧 Extracting from message type: {type(message)}")
            logger.debug(f"🔧 Message content preview: {str(message)[:100]}")
            
            # Handle a2a_json_rpc.spec.Message objects (the problematic case!)
            if hasattr(message, 'parts') and message.parts:
                text_parts = []
                for part in message.parts:
                    # Check for part.text first (standard case)
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text.strip())
                        continue
                    
                    # Check for part.root['text'] (the actual structure we're seeing!)
                    if hasattr(part, 'root') and isinstance(part.root, dict):
                        if part.root.get('type') == 'text' and part.root.get('text'):
                            text_parts.append(part.root['text'].strip())
                            continue
                    
                    # Check if part itself is a dict with text
                    if isinstance(part, dict) and part.get('text'):
                        text_parts.append(part['text'].strip())
                        continue
                
                if text_parts:
                    result = ' '.join(text_parts)
                    logger.debug(f"🔧 Extracted from Message.parts: '{result[:50]}...'")
                    return result
            
            # Handle dictionary with parts
            elif isinstance(message, dict) and message.get('parts'):
                text_parts = []
                for part in message['parts']:
                    if isinstance(part, dict) and part.get('text'):
                        text_parts.append(part['text'].strip())
                result = ' '.join(text_parts)
                logger.debug(f"🔧 Extracted from dict.parts: '{result[:50]}...'")
                return result
            
            # Handle direct dictionary with text
            elif isinstance(message, dict) and message.get('text'):
                result = message['text'].strip()
                logger.debug(f"🔧 Extracted from dict.text: '{result[:50]}...'")
                return result
            
            # Handle string message
            elif isinstance(message, str):
                result = message.strip()
                logger.debug(f"🔧 Extracted from string: '{result[:50]}...'")
                return result
            
            # Fallback: convert to string
            result = str(message)[:200] if message else ""
            logger.debug(f"🔧 Fallback extraction: '{result[:50]}...'")
            return result
            
        except Exception as e:
            logger.warning(f"🔧 Message extraction failed: {e}")
            fallback = str(message)[:50] if message else ""
            logger.debug(f"🔧 Exception fallback: '{fallback}...'")
            return fallback
    
    def _normalize_session_id(self, session_id: str) -> str:
        """
        Normalize session ID for consistent deduplication.
        
        This treats common default/placeholder session IDs as equivalent
        to handle client inconsistencies while preserving real session boundaries.
        """
        if not session_id:
            return "default"
        
        # Normalize common default/placeholder values
        if session_id.lower() in ["default", "null", "none", "undefined"]:
            return "default"
        
        # STRENGTHENED: If it looks like a random UUID/hash (32+ hex chars), treat as default
        # This handles clients that generate random session IDs for each request
        if len(session_id) >= 32 and all(c in '0123456789abcdefABCDEF' for c in session_id):
            logger.debug(f"🔧 Treating random-looking session '{session_id[:8]}...' as default")
            return "default"
        
        # Normalize very short session IDs (likely auto-generated placeholders)
        if len(session_id) < 8:
            return "default"
        
        # For real session IDs, keep them as-is to maintain session boundaries
        return session_id
    
    def _create_dedup_key(self, session_id: str, message, handler: str) -> str:
        """Create deduplication key with proper message extraction."""
        message_text = self._extract_message_text(message)
        normalized_text = ' '.join(message_text.split())
        
        # Handle empty message extraction
        if not normalized_text:
            logger.warning(f"🔧 Empty message extracted from {type(message)}")
            normalized_text = "empty_message"
        
        # Normalize session ID to handle client inconsistencies
        normalized_session = self._normalize_session_id(session_id)
        
        content = f"{normalized_session}:{handler}:{normalized_text}"
        dedup_key = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        # DEBUG: Log the components used for deduplication
        logger.debug(f"🔧 Dedup components: session='{normalized_session}', handler='{handler}', message='{normalized_text[:50]}...'")
        
        return dedup_key
    
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
        
        normalized_session = self._normalize_session_id(session_id)
        logger.debug(f"🔍 Dedup check: key={dedup_key}, session={normalized_session}, handler={handler}")
        
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
                normalized_session = self._normalize_session_id(session_id)
                new_data = {
                    'task_id': task_id,
                    'timestamp': time.time(),
                    'handler': handler,
                    'session_id': normalized_session,
                    'original_session_id': session_id  # Keep original for debugging
                }
                
                ttl_seconds = int(self.window_seconds * 2)
                await session.setex(storage_key, ttl_seconds, json.dumps(new_data))
                
                logger.debug(f"✅ Recorded dedup entry: {storage_key} -> {task_id} (TTL: {ttl_seconds}s)")
                return True
                
        except Exception as e:
            logger.warning(f"❌ Failed to record dedup entry: {e}")
            return False

    def get_stats(self) -> dict:
        """Get deduplication statistics."""
        return {
            "window_seconds": self.window_seconds,
            "status": "active",
            "storage_method": "session_manager_provider",
            "session_normalization": "enabled"
        }

# Global deduplicator instance
deduplicator = SessionDeduplicator(window_seconds=3.0)

# Export for import
__all__ = ["SessionDeduplicator", "deduplicator"]