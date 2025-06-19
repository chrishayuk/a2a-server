# a2a_server/tasks/handlers/adk/google_adk_handler.py (FIXED)
"""
Google ADK Handler - Resilient wrapper for Google ADK agents.

This handler provides resilience for Google ADK agents, automatically wrapping
raw ADK agents and providing ADK-optimized settings with session support.
"""
import logging
from typing import Optional, Dict, Any

from a2a_server.tasks.handlers.resilient_handler import ResilientHandler

logger = logging.getLogger(__name__)


class GoogleADKHandler(ResilientHandler):
    """
    Resilient Google ADK Handler with ADK-optimized settings and session support.
    
    This handler automatically wraps raw ADK agents and provides resilience
    with settings optimized for ADK agents' typical usage patterns.
    """
    
    def __init__(
        self,
        agent,  # Raw ADK agent or already wrapped handler
        name: Optional[str] = None,
        circuit_breaker_threshold: int = 3,  # ADK agents are more stable
        circuit_breaker_timeout: float = 180.0,  # Longer recovery time
        task_timeout: float = 240.0,  # 4 minutes for ADK operations
        max_retry_attempts: int = 2,  # Standard retry count
        recovery_check_interval: float = 300.0,  # Check every 5 minutes
        # ADK-specific settings
        use_sessions: bool = False,
        token_threshold: int = 4000,
        summarization_strategy: str = "key_points",
        session_store=None,
        # Session parameters that need to be passed through
        sandbox_id: Optional[str] = None,
        infinite_context: bool = True,
        max_turns_per_segment: int = 50,
        default_ttl_hours: int = 24,
        **kwargs
    ):
        """
        Initialize Google ADK handler with resilience.
        
        Args:
            agent: Google ADK agent instance (raw or wrapped)
            name: Handler name (auto-detected if None)
            circuit_breaker_threshold: Failures before circuit opens (default: 3)
            circuit_breaker_timeout: Circuit open time (default: 180s)
            task_timeout: Max time per task (default: 240s)
            max_retry_attempts: Max retries (default: 2)
            recovery_check_interval: Recovery check frequency (default: 300s)
            use_sessions: Whether to enable session support
            token_threshold: Token limit for session management
            summarization_strategy: How to summarize long conversations
            session_store: Optional session store to use
            sandbox_id: Session sandbox ID (CRITICAL for shared sessions)
            infinite_context: Whether to use infinite context
            max_turns_per_segment: Max turns per segment
            default_ttl_hours: Default TTL for sessions
            **kwargs: Additional arguments
        """
        # Store ADK-specific settings
        self.use_sessions = use_sessions
        self.token_threshold = token_threshold
        self.summarization_strategy = summarization_strategy
        self.session_store = session_store
        
        # Wrap the agent if needed
        wrapped_agent = self._wrap_adk_agent(agent)
        
        # CRITICAL: Pass session parameters to ResilientHandler if sessions are enabled
        session_kwargs = {}
        if use_sessions:
            session_kwargs.update({
                'sandbox_id': sandbox_id,
                'infinite_context': infinite_context,
                'token_threshold': token_threshold,
                'max_turns_per_segment': max_turns_per_segment,
                'default_ttl_hours': default_ttl_hours,
                'session_store': session_store,
            })
            logger.info(f"🔗 ADK agent '{name}' using external sessions with sandbox: {sandbox_id}")
        else:
            logger.info(f"🔧 ADK agent '{name}' using internal ADK sessions only")
        
        super().__init__(
            agent=wrapped_agent,
            name=name or "google_adk",
            circuit_breaker_threshold=circuit_breaker_threshold,
            circuit_breaker_timeout=circuit_breaker_timeout,
            task_timeout=task_timeout,
            max_retry_attempts=max_retry_attempts,
            recovery_check_interval=recovery_check_interval,
            **session_kwargs,  # ← CRITICAL: Pass session parameters
            **kwargs
        )
        
        logger.info(f"Initialized GoogleADKHandler '{self._name}' with ADK-optimized settings")
    
    def _wrap_adk_agent(self, agent):
        """Wrap ADK agent with the ADKAgentAdapter if needed."""
        # If it already has invoke/stream methods, it's already wrapped
        if hasattr(agent, 'invoke') and hasattr(agent, 'stream'):
            logger.info(f"🔧 Agent already has invoke/stream methods: {type(agent)}")
            return agent
        
        # If it's already a TaskHandler (has process_task), use it directly
        if hasattr(agent, 'process_task'):
            logger.info(f"🔧 Agent is already a TaskHandler: {type(agent)}")
            return agent
        
        # Check if it's a raw Google ADK Agent
        if self._is_raw_adk_agent(agent):
            try:
                # Import and wrap with ADKAgentAdapter
                from a2a_server.tasks.handlers.adk.adk_agent_adapter import ADKAgentAdapter
                
                wrapped = ADKAgentAdapter(agent)
                logger.info(f"✅ Wrapped raw ADK agent with ADKAgentAdapter: {type(agent)} -> {type(wrapped)}")
                return wrapped
                
            except ImportError as e:
                logger.error(f"❌ Could not import ADKAgentAdapter: {e}")
                return agent
            except Exception as e:
                logger.error(f"❌ Failed to wrap ADK agent: {e}")
                return agent
        
        # Otherwise, use the agent directly and hope for the best
        logger.warning(f"⚠️ Using agent directly without wrapping: {type(agent)}")
        return agent
    
    def _is_raw_adk_agent(self, agent) -> bool:
        """Check if this is a raw Google ADK Agent that needs wrapping."""
        try:
            # Check for ADK Agent class or module
            agent_class = agent.__class__
            module_name = agent_class.__module__
            class_name = agent_class.__name__
            
            # Look for Google ADK indicators
            adk_indicators = [
                'google.adk',
                'Agent',  # Common ADK class name
            ]
            
            is_adk = any(indicator in module_name or indicator in class_name for indicator in adk_indicators)
            
            # Additional check: ADK agents typically have name, model, instruction attributes
            has_adk_attrs = (
                hasattr(agent, 'name') and 
                hasattr(agent, 'model') and 
                (hasattr(agent, 'instruction') or hasattr(agent, 'description'))
            )
            
            result = is_adk and has_adk_attrs
            
            if result:
                logger.info(f"🔍 Detected raw ADK agent: {class_name} from {module_name}")
            else:
                logger.debug(f"🔍 Not a raw ADK agent: {class_name} from {module_name}")
            
            return result
            
        except Exception as e:
            logger.debug(f"🔍 Error checking if agent is raw ADK: {e}")
            return False


# Export class
__all__ = ["GoogleADKHandler"]