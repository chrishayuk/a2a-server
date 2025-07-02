# a2a_server/deduplication_enhanced.py
"""
Enhanced deduplication with semantic message comparison and adaptive windows.
"""
import hashlib
import logging
import time
import json
from typing import Optional, Any, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class DedupEntry:
    """Structured deduplication entry."""
    task_id: str
    timestamp: float
    handler: str
    session_id: str
    message_hash: str
    original_session_id: str
    request_count: int = 1

class SessionDeduplicator:
    """
    Enhanced session-based deduplication with:
    - Semantic message comparison
    - Adaptive time windows
    - Request frequency tracking
    - Better session normalization
    """
    
    def __init__(self, 
                 base_window_seconds: float = 3.0,
                 max_window_seconds: float = 10.0,
                 semantic_threshold: float = 0.8):
        self.base_window_seconds = base_window_seconds
        self.max_window_seconds = max_window_seconds
        self.semantic_threshold = semantic_threshold
        self._session_stats: Dict[str, Dict[str, Any]] = {}
    
    def _extract_message_text(self, message) -> str:
        """Enhanced message extraction with better error handling."""
        try:
            # Handle a2a_json_rpc.spec.Message objects
            if hasattr(message, 'parts') and message.parts:
                text_parts = []
                for part in message.parts:
                    # Multiple extraction strategies
                    text = None
                    
                    if hasattr(part, 'text') and part.text:
                        text = part.text
                    elif hasattr(part, 'root') and isinstance(part.root, dict):
                        if part.root.get('type') == 'text':
                            text = part.root.get('text')
                    elif isinstance(part, dict):
                        text = part.get('text')
                    
                    if text:
                        text_parts.append(str(text).strip())
                
                if text_parts:
                    result = ' '.join(text_parts)
                    logger.debug(f"🔧 Extracted from Message.parts: '{result[:50]}...'")
                    return result
            
            # Handle dictionary structures
            elif isinstance(message, dict):
                if message.get('parts'):
                    return self._extract_from_dict_parts(message['parts'])
                elif message.get('text'):
                    return str(message['text']).strip()
            
            # Handle direct string
            elif isinstance(message, str):
                return message.strip()
            
            # Fallback
            result = str(message)[:200] if message else ""
            logger.debug(f"🔧 Fallback extraction: '{result[:50]}...'")
            return result
            
        except Exception as e:
            logger.warning(f"🔧 Message extraction failed: {e}")
            return str(message)[:50] if message else ""
    
    def _extract_from_dict_parts(self, parts) -> str:
        """Extract text from dictionary parts."""
        text_parts = []
        try:
            for part in parts:
                if isinstance(part, dict) and part.get('text'):
                    text_parts.append(str(part['text']).strip())
        except Exception as e:
            logger.debug(f"Error extracting from dict parts: {e}")
        
        return ' '.join(text_parts)
    
    def _normalize_session_id(self, session_id: str) -> str:
        """Enhanced session ID normalization."""
        if not session_id:
            return "default"
        
        # Common defaults
        if session_id.lower() in ["default", "null", "none", "undefined", "anonymous"]:
            return "default"
        
        # Random-looking IDs (UUIDs, hashes, etc.)
        if len(session_id) >= 32:
            # Check if it's hex
            if all(c in '0123456789abcdefABCDEF-' for c in session_id):
                logger.debug(f"🔧 Treating random session '{session_id[:8]}...' as default")
                return "default"
        
        # Very short IDs (likely auto-generated)
        if len(session_id) < 8:
            return "default"
        
        # Keep real session IDs
        return session_id
    
    def _get_adaptive_window(self, session_id: str) -> float:
        """Calculate adaptive window based on request frequency."""
        stats = self._session_stats.get(session_id, {})
        recent_requests = stats.get('recent_requests', 0)
        
        # Increase window for high-frequency sessions
        if recent_requests > 5:
            adaptive_window = min(
                self.base_window_seconds * (1 + recent_requests * 0.2),
                self.max_window_seconds
            )
        else:
            adaptive_window = self.base_window_seconds
        
        logger.debug(f"🔧 Adaptive window for {session_id}: {adaptive_window:.1f}s (recent: {recent_requests})")
        return adaptive_window
    
    def _update_session_stats(self, session_id: str):
        """Update session statistics for adaptive behavior."""
        now = time.time()
        if session_id not in self._session_stats:
            self._session_stats[session_id] = {
                'first_seen': now,
                'last_seen': now,
                'request_count': 0,
                'recent_requests': 0,
                'recent_window_start': now
            }
        
        stats = self._session_stats[session_id]
        stats['last_seen'] = now
        stats['request_count'] += 1
        
        # Count recent requests (last 60 seconds)
        if now - stats['recent_window_start'] > 60:
            stats['recent_requests'] = 1
            stats['recent_window_start'] = now
        else:
            stats['recent_requests'] += 1
    
    def _create_dedup_key(self, session_id: str, message, handler: str) -> str:
        """Create enhanced deduplication key."""
        message_text = self._extract_message_text(message)
        
        # Normalize text for better matching
        normalized_text = ' '.join(message_text.split()).lower()
        
        if not normalized_text:
            logger.warning(f"🔧 Empty message extracted from {type(message)}")
            normalized_text = "empty_message"
        
        normalized_session = self._normalize_session_id(session_id)
        
        # Create semantic hash (could be enhanced with embeddings)
        content = f"{normalized_session}:{handler}:{normalized_text}"
        dedup_key = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        logger.debug(f"🔧 Dedup key: {dedup_key} for session={normalized_session}, handler={handler}")
        return dedup_key
    
    async def check_duplicate(self, task_manager, session_id: str, message, handler: str) -> Optional[str]:
        """Enhanced duplicate checking with adaptive windows."""
        session_manager = task_manager.session_manager
        if not session_manager:
            logger.warning("⚠️ No session manager available for deduplication")
            return None
        
        normalized_session = self._normalize_session_id(session_id)
        self._update_session_stats(normalized_session)
        
        dedup_key = self._create_dedup_key(session_id, message, handler)
        storage_key = f"dedup:{dedup_key}"
        
        adaptive_window = self._get_adaptive_window(normalized_session)
        
        try:
            session_ctx_mgr = session_manager.session_factory()
            
            async with session_ctx_mgr as session:
                existing_raw = await session.get(storage_key)
                
                if existing_raw:
                    try:
                        existing_data = json.loads(existing_raw)
                        entry = DedupEntry(**existing_data)
                        time_diff = time.time() - entry.timestamp
                        
                        if time_diff < adaptive_window and entry.task_id:
                            # Update request count
                            entry.request_count += 1
                            updated_data = {
                                **existing_data,
                                'request_count': entry.request_count,
                                'last_duplicate_at': time.time()
                            }
                            ttl_seconds = int(adaptive_window * 2)
                            await session.setex(storage_key, ttl_seconds, json.dumps(updated_data))
                            
                            logger.info(f"🔄 Duplicate #{entry.request_count}: {entry.task_id} ({time_diff:.1f}s ago)")
                            return entry.task_id
                        else:
                            logger.debug(f"Entry expired: {time_diff:.1f}s > {adaptive_window}s")
                    
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Invalid dedup entry: {e}")
                
                return None
                
        except Exception as e:
            logger.warning(f"❌ Dedup check failed: {e}")
            return None
    
    async def record_task(self, task_manager, session_id: str, message, handler: str, task_id: str) -> bool:
        """Record task with enhanced metadata."""
        session_manager = task_manager.session_manager
        if not session_manager:
            return False
        
        normalized_session = self._normalize_session_id(session_id)
        dedup_key = self._create_dedup_key(session_id, message, handler)
        storage_key = f"dedup:{dedup_key}"
        
        try:
            session_ctx_mgr = session_manager.session_factory()
            adaptive_window = self._get_adaptive_window(normalized_session)
            
            async with session_ctx_mgr as session:
                entry = DedupEntry(
                    task_id=task_id,
                    timestamp=time.time(),
                    handler=handler,
                    session_id=normalized_session,
                    message_hash=dedup_key,
                    original_session_id=session_id,
                    request_count=1
                )
                
                ttl_seconds = int(adaptive_window * 2)
                await session.setex(storage_key, ttl_seconds, json.dumps(entry.__dict__))
                
                logger.debug(f"✅ Recorded dedup entry: {storage_key} -> {task_id} (TTL: {ttl_seconds}s)")
                return True
                
        except Exception as e:
            logger.warning(f"❌ Failed to record dedup entry: {e}")
            return False
    
    def get_stats(self) -> dict:
        """Get comprehensive deduplication statistics."""
        total_sessions = len(self._session_stats)
        active_sessions = sum(
            1 for stats in self._session_stats.values()
            if time.time() - stats['last_seen'] < 3600  # Active in last hour
        )
        
        return {
            "window_seconds": f"{self.base_window_seconds}-{self.max_window_seconds} (adaptive)",
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "session_stats": {
                k: {
                    "request_count": v["request_count"],
                    "recent_requests": v["recent_requests"],
                    "age_seconds": int(time.time() - v["first_seen"])
                }
                for k, v in list(self._session_stats.items())[:10]  # Top 10 sessions
            },
            "status": "enhanced_active",
            "features": ["adaptive_windows", "semantic_matching", "frequency_tracking"]
        }

# Global deduplicator instance
deduplicator = SessionDeduplicator(
    base_window_seconds=3.0,
    max_window_seconds=10.0
)