# File: a2a_server/utils/session_sandbox.py
"""
Session sandbox utility for consistent naming and configuration.
"""
from __future__ import annotations

import os
import re
from typing import Optional


class SessionSandbox:
    """Utility class for managing session sandbox names and configuration."""
    
    # Default prefixes for different types of sandboxes
    HANDLER_PREFIX = "a2a-handler"
    SERVER_PREFIX = "a2a-server"
    AI_PREFIX = "ai-session"
    
    @classmethod
    def for_handler(cls, handler_name: str, prefix: Optional[str] = None) -> str:
        """
        Generate a sandbox name for a task handler.
        
        Args:
            handler_name: Name of the handler
            prefix: Optional custom prefix (defaults to 'a2a-handler')
            
        Returns:
            Sanitized sandbox name
        """
        prefix = prefix or cls.HANDLER_PREFIX
        return cls._sanitize_name(f"{prefix}-{handler_name}")
    
    @classmethod
    def for_server(cls, server_name: Optional[str] = None) -> str:
        """
        Generate a sandbox name for the A2A server.
        
        Args:
            server_name: Optional server identifier
            
        Returns:
            Sanitized sandbox name
        """
        if server_name:
            return cls._sanitize_name(f"{cls.SERVER_PREFIX}-{server_name}")
        return cls.SERVER_PREFIX
    
    @classmethod
    def for_ai_session(cls, session_type: str = "manager") -> str:
        """
        Generate a sandbox name for AI session management.
        
        Args:
            session_type: Type of AI session (e.g., 'manager', 'storage')
            
        Returns:
            Sanitized sandbox name
        """
        return cls._sanitize_name(f"{cls.AI_PREFIX}-{session_type}")
    
    @classmethod
    def from_config(cls, config: dict, handler_name: str) -> str:
        """
        Generate sandbox name from configuration.
        
        Args:
            config: Configuration dictionary
            handler_name: Handler name as fallback
            
        Returns:
            Sandbox name from config or generated default
        """
        # Check for explicit sandbox_id in config
        if "sandbox_id" in config:
            return cls._sanitize_name(config["sandbox_id"])
        
        # Check for handler-specific sandbox pattern
        if "sandbox_prefix" in config:
            return cls.for_handler(handler_name, config["sandbox_prefix"])
        
        # Default to handler-based sandbox
        return cls.for_handler(handler_name)
    
    @classmethod
    def from_env(cls, env_var: str, fallback_name: str) -> str:
        """
        Get sandbox name from environment variable with fallback.
        
        Args:
            env_var: Environment variable name
            fallback_name: Fallback name if env var not set
            
        Returns:
            Sandbox name from env or fallback
        """
        env_value = os.getenv(env_var)
        if env_value:
            return cls._sanitize_name(env_value)
        return cls.for_handler(fallback_name)
    
    @classmethod
    def _sanitize_name(cls, name: str) -> str:
        """
        Sanitize sandbox name to ensure it's valid.
        
        Args:
            name: Raw sandbox name
            
        Returns:
            Sanitized name (lowercase, alphanumeric + hyphens)
        """
        # Convert to lowercase
        name = name.lower()
        
        # Replace invalid characters with hyphens
        name = re.sub(r'[^a-z0-9\-_]', '-', name)
        
        # Remove consecutive hyphens
        name = re.sub(r'-+', '-', name)
        
        # Remove leading/trailing hyphens
        name = name.strip('-')
        
        # Ensure minimum length
        if not name:
            name = "default-sandbox"
        
        return name
    
    @classmethod
    def validate(cls, name: str) -> bool:
        """
        Validate if a sandbox name is properly formatted.
        
        Args:
            name: Sandbox name to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not name:
            return False
        
        # Check pattern: lowercase alphanumeric + hyphens/underscores
        if not re.match(r'^[a-z0-9\-_]+$', name):
            return False
        
        # Check length (reasonable limits)
        if len(name) < 1 or len(name) > 63:  # DNS label limits
            return False
        
        # Check doesn't start/end with hyphen
        if name.startswith('-') or name.endswith('-'):
            return False
        
        return True


# Convenience functions for common use cases
def handler_sandbox(handler_name: str, config: Optional[dict] = None) -> str:
    """Get sandbox name for a handler with optional config."""
    if config:
        return SessionSandbox.from_config(config, handler_name)
    return SessionSandbox.for_handler(handler_name)

def server_sandbox(server_name: Optional[str] = None) -> str:
    """Get sandbox name for the server."""
    return SessionSandbox.for_server(server_name)

def ai_sandbox(session_type: str = "manager") -> str:
    """Get sandbox name for AI session management."""
    return SessionSandbox.for_ai_session(session_type)