# a2a/server/logging.py
import logging
import sys
from typing import Optional, List, Dict

def configure_logging(
    level_name: str = "info", 
    file_path: Optional[str] = None,
    verbose_modules: Optional[List[str]] = None,
    quiet_modules: Optional[Dict[str, str]] = None
) -> None:
    """
    Configure logging for the A2A server.
    
    Args:
        level_name: Log level (debug, info, warning, error, critical)
        file_path: Optional path to write logs to a file
        verbose_modules: Optional list of module names to log at DEBUG level
                         regardless of the global setting
        quiet_modules: Optional dict of module names with their specific log level
                      that should be higher than the global level
    """
    # Convert log level string to numeric value
    root_level = getattr(logging, level_name.upper(), logging.INFO)
    
    # Create handlers
    handlers = []
    
    # Always log to console
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(root_level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
    ))
    handlers.append(console)
    
    # Optionally log to file
    if file_path:
        file_handler = logging.FileHandler(file_path)
        file_handler.setLevel(root_level)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
        ))
        handlers.append(file_handler)
    
    # Clear any existing handlers from the root logger
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        
    # Configure root logger
    root_logger.setLevel(root_level)
    for handler in handlers:
        root_logger.addHandler(handler)
    
    # Set specific loggers to DEBUG if requested
    if verbose_modules:
        for module_name in verbose_modules:
            module_logger = logging.getLogger(module_name)
            module_logger.setLevel(logging.DEBUG)
    
    # Common noisy modules to quiet down by default
    DEFAULT_QUIET_MODULES = {
        # Framework-related loggers
        "asyncio": "WARNING",
        "uvicorn": "WARNING", 
        "uvicorn.access": "WARNING",
        "fastapi": "WARNING",
        "httpx": "ERROR",         # Quieter by default - ERROR only
        
        # Google ADK-related loggers
        "google": "WARNING",
        "google.adk": "WARNING",
        "google.adk.models": "WARNING",
        "google.adk.models.lite_llm": "ERROR",  # Quieter by default - ERROR only
        "google.adk.runners": "WARNING",
        "google.adk.sessions": "WARNING",
        "google.adk.artifacts": "WARNING",
        "google.adk.memory": "WARNING",
        "google.adk.agents": "WARNING",
        "google.genai": "WARNING",
        
        # LiteLLM-related loggers
        "LiteLLM": "ERROR",       # Quieter by default - ERROR only
        "litellm": "ERROR",       # Quieter by default - ERROR only
        "litellm.utils": "ERROR", # Quieter by default - ERROR only
        "litellm.llms": "ERROR",  # Quieter by default - ERROR only
    }
    
    # Apply defaults except where overridden in quiet_modules
    quiet_modules = quiet_modules or {}
    for module_name, level_name in DEFAULT_QUIET_MODULES.items():
        if module_name not in quiet_modules:
            level = getattr(logging, level_name.upper(), None)
            if level is not None:
                module_logger = logging.getLogger(module_name)
                module_logger.setLevel(level)
    
    # Apply user-specified quiet modules (these override defaults)
    for module_name, level_name in quiet_modules.items():
        level = getattr(logging, level_name.upper(), None)
        if level is not None:
            module_logger = logging.getLogger(module_name)
            module_logger.setLevel(level)