# a2a_server/tasks/handlers/chuk/chuk_agent_handler.py
"""
ChukAgent Handler - Specialized wrapper around ResilientHandler for ChukAgents with session sharing support.

This provides ChukAgent-optimized defaults while maintaining backward compatibility.
"""
import logging
from typing import Optional

from a2a_server.tasks.handlers.resilient_handler import ResilientHandler

logger = logging.getLogger(__name__)


class ChukAgentHandler(ResilientHandler):
    """
    ChukAgent Handler with ChukAgent-optimized resilience settings and session sharing support.
    
    This is a thin wrapper around ResilientHandler with settings optimized
    for ChukAgents that typically use tools and may have MCP connections.
    """
    
    def __init__(
        self, 
        agent=None, 
        name: Optional[str] = None,
        circuit_breaker_threshold: int = 2,  # ChukAgents fail fast for tool issues
        circuit_breaker_timeout: float = 60.0,  # Quick recovery for tools
        task_timeout: float = 180.0,  # 3 minutes for complex tool operations
        max_retry_attempts: int = 1,  # Don't over-retry tool operations
        recovery_check_interval: float = 120.0,  # Check every 2 minutes
        sandbox_id: Optional[str] = None,  # Session sandbox ID
        # NEW: Session sharing configuration
        session_sharing: Optional[bool] = None,  # Enable/disable cross-agent session sharing
        shared_sandbox_group: Optional[str] = None,  # Shared sandbox group for cross-agent sessions
        **kwargs
    ):
        """
        Initialize ChukAgent handler with optimized settings and session sharing support.
        
        Args:
            agent: ChukAgent instance or import path
            name: Handler name (auto-detected if None)
            circuit_breaker_threshold: Failures before circuit opens (default: 2)
            circuit_breaker_timeout: Circuit open time (default: 60s)
            task_timeout: Max time per task (default: 180s)
            max_retry_attempts: Max retries (default: 1)
            recovery_check_interval: Recovery check frequency (default: 120s)
            sandbox_id: Session sandbox ID for isolated sessions
            session_sharing: Enable cross-agent session sharing (default: None = auto-detect)
            shared_sandbox_group: Shared sandbox group name for cross-agent sessions
            **kwargs: Additional arguments
        """
        
        # *** KEY FIX: Explicit session sharing detection ***
        if shared_sandbox_group and session_sharing is None:
            # Auto-enable session sharing when shared_sandbox_group is provided
            session_sharing = True
            logger.info(f"Auto-enabling session sharing for shared_sandbox_group: {shared_sandbox_group}")
        
        # *** KEY FIX: Pass session sharing parameters to parent ***
        super().__init__(
            agent=agent,
            name=name or "chuk_agent",
            circuit_breaker_threshold=circuit_breaker_threshold,
            circuit_breaker_timeout=circuit_breaker_timeout,
            task_timeout=task_timeout,
            max_retry_attempts=max_retry_attempts,
            recovery_check_interval=recovery_check_interval,
            sandbox_id=sandbox_id,
            session_sharing=session_sharing,
            shared_sandbox_group=shared_sandbox_group,
            **kwargs
        )
        
        # Log session sharing configuration
        if self.session_sharing:
            logger.info(f"Initialized ChukAgentHandler '{self._name}' with SHARED sessions (group: {self.shared_sandbox_group})")
        else:
            logger.info(f"Initialized ChukAgentHandler '{self._name}' with ISOLATED sessions (sandbox: {self.sandbox_id})")


# Backward compatibility alias
class AgentHandler(ChukAgentHandler):
    """Alias for ChukAgentHandler to maintain backward compatibility."""
    pass


# Export classes
__all__ = ["ChukAgentHandler", "AgentHandler"]