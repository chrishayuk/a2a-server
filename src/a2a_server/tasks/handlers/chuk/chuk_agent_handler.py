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
            agent: ChukAgent instance or import path or factory function
            name: Handler name (auto-detected if None)
            circuit_breaker_threshold: Failures before circuit opens (default: 2)
            circuit_breaker_timeout: Circuit open time (default: 60s)
            task_timeout: Max time per task (default: 180s)
            max_retry_attempts: Max retries (default: 1)
            recovery_check_interval: Recovery check frequency (default: 120s)
            sandbox_id: Session sandbox ID for isolated sessions
            session_sharing: Enable cross-agent session sharing (default: None = auto-detect)
            shared_sandbox_group: Shared sandbox group name for cross-agent sessions
            **kwargs: Additional arguments (including agent factory parameters)
        """
        
        # 🔧 NEW: Handle agent factory function with parameters
        processed_agent = self._process_agent_with_params(agent, kwargs)
        
        # Extract handler-specific parameters and remove agent factory parameters
        handler_kwargs = self._extract_handler_params(kwargs)
        
        # *** KEY FIX: Explicit session sharing detection ***
        if shared_sandbox_group and session_sharing is None:
            # Auto-enable session sharing when shared_sandbox_group is provided
            session_sharing = True
            logger.info(f"Auto-enabling session sharing for shared_sandbox_group: {shared_sandbox_group}")
        
        # *** KEY FIX: Pass session sharing parameters to parent ***
        super().__init__(
            agent=processed_agent,  # Use the processed agent (with parameters applied)
            name=name or "chuk_agent",
            circuit_breaker_threshold=circuit_breaker_threshold,
            circuit_breaker_timeout=circuit_breaker_timeout,
            task_timeout=task_timeout,
            max_retry_attempts=max_retry_attempts,
            recovery_check_interval=recovery_check_interval,
            sandbox_id=sandbox_id,
            session_sharing=session_sharing,
            shared_sandbox_group=shared_sandbox_group,
            **handler_kwargs  # Only pass handler-specific parameters
        )
        
        # Log session sharing configuration
        if self.session_sharing:
            logger.info(f"Initialized ChukAgentHandler '{self._name}' with SHARED sessions (group: {self.shared_sandbox_group})")
        else:
            logger.info(f"Initialized ChukAgentHandler '{self._name}' with ISOLATED sessions (sandbox: {self.sandbox_id})")

    def _process_agent_with_params(self, agent, kwargs):
        """
        Process the agent parameter, handling factory functions with parameters.
        
        Args:
            agent: Agent instance, import path, or factory function
            kwargs: All configuration parameters from YAML
            
        Returns:
            Processed agent instance
        """
        # If agent is callable (factory function), call it with appropriate parameters
        if callable(agent):
            agent_params = self._extract_agent_params(kwargs)
            logger.info(f"🔧 Calling agent factory with parameters: {list(agent_params.keys())}")
            logger.debug(f"🔧 Agent factory parameters: {agent_params}")
            
            try:
                processed_agent = agent(**agent_params)
                logger.info(f"✅ Successfully created agent via factory function")
                return processed_agent
            except Exception as e:
                logger.error(f"❌ Failed to create agent via factory function: {e}")
                raise
        else:
            # Agent is already an instance or import path, use as-is
            logger.info(f"🔧 Using agent directly (not a factory function)")
            return agent

    def _extract_agent_params(self, kwargs):
        """
        Extract parameters that should be passed to the agent factory function.
        
        Args:
            kwargs: All configuration parameters from YAML
            
        Returns:
            Dictionary of parameters for agent factory
        """
        # Define which parameters should be passed to the agent factory
        agent_param_keys = {
            # Session management parameters
            'enable_sessions',
            'infinite_context', 
            'token_threshold',
            'max_turns_per_segment',
            'session_ttl_hours',
            
            # Model parameters
            'provider',
            'model',
            'streaming',
            
            # Tool parameters
            'enable_tools',
            'debug_tools',
            
            # MCP parameters
            'mcp_transport',
            'mcp_config_file',
            'mcp_servers',
            'mcp_sse_servers',
            'tool_namespace',
            'max_concurrency',
            'tool_timeout',
            
            # Other agent-specific parameters
            'description',
            'instruction',
            'use_system_prompt_generator',
        }
        
        # Extract only the parameters that should go to the agent factory
        agent_params = {k: v for k, v in kwargs.items() if k in agent_param_keys}
        
        logger.debug(f"🔧 Extracted {len(agent_params)} agent parameters from {len(kwargs)} total kwargs")
        return agent_params

    def _extract_handler_params(self, kwargs):
        """
        Extract parameters that should be passed to the handler (not agent factory).
        
        Args:
            kwargs: All configuration parameters from YAML
            
        Returns:
            Dictionary of parameters for handler
        """
        # Define which parameters are for the agent factory (to exclude)
        agent_param_keys = {
            'enable_sessions', 'infinite_context', 'token_threshold', 'max_turns_per_segment',
            'session_ttl_hours', 'provider', 'model', 'streaming', 'enable_tools', 'debug_tools',
            'mcp_transport', 'mcp_config_file', 'mcp_servers', 'mcp_sse_servers', 'tool_namespace',
            'max_concurrency', 'tool_timeout', 'description', 'instruction', 'use_system_prompt_generator'
        }
        
        # Return only non-agent parameters
        handler_params = {k: v for k, v in kwargs.items() if k not in agent_param_keys}
        
        logger.debug(f"🔧 Extracted {len(handler_params)} handler parameters from {len(kwargs)} total kwargs")
        return handler_params


# Backward compatibility alias
class AgentHandler(ChukAgentHandler):
    """Alias for ChukAgentHandler to maintain backward compatibility."""
    pass


# Export classes
__all__ = ["ChukAgentHandler", "AgentHandler"]