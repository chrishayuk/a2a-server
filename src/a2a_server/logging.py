# a2a_server/logging.py - Fixed version without duplicates

from __future__ import annotations

import logging
import os
import sys
import warnings
from typing import Dict, List, Optional
from pythonjsonlogger.json import JsonFormatter as _JsonFormatter  # type: ignore

__all__ = ["configure_logging"]

# ---------------------------------------------------------------------------
# Default per-module level tweaks - FIXED DUPLICATES
# ---------------------------------------------------------------------------
_DEFAULT_QUIET_MODULES: Dict[str, str] = {
    "asyncio": "ERROR",
    "uvicorn": "WARNING",
    "uvicorn.access": "WARNING", 
    "fastapi": "WARNING",
    "httpx": "ERROR",
    
    # Google ADK noise
    "google": "WARNING",
    "google.adk": "WARNING",
    "google.adk.models": "ERROR",
    "google.adk.models.registry": "ERROR",
    
    # LiteLLM noise
    "LiteLLM": "ERROR",
    "litellm": "ERROR",
    
    # CHUK modules - Quiet the noise but keep errors
    "chuk_sessions": "WARNING",
    "chuk_sessions.session_manager": "ERROR",
    "chuk_ai_session_manager": "ERROR", 
    "chuk_ai_session_manager.session_storage": "ERROR",
    "chuk_llm": "WARNING",
    
    # CHUK Tool Processor - Silence the span logging but keep tool execution results
    "chuk_tool_processor.span": "ERROR",  # Removes start/complete spam
    "chuk_tool_processor.span.inprocess_execution": "ERROR",  # The main offender
    "chuk_tool_processor.mcp.stream_manager": "ERROR",  # Reduces MCP init noise
    "chuk_tool_processor.mcp.setup_sse": "WARNING", # Keep connection info
    "chuk_tool_processor.mcp.register": "WARNING",  # Keep tool registration
    
    # A2A internal modules - Keep important ones visible
    "a2a_server.transport": "WARNING",
    "a2a_server.session_store_factory": "WARNING",
    "a2a_server.tasks.handlers.session_aware_task_handler": "WARNING",
    "a2a_server.tasks.handlers.chuk.chuk_agent": "INFO",  # Keep for debugging
    "a2a_server.handlers_setup": "WARNING",
    "a2a_server.tasks.discovery": "ERROR",
    
    # Sample agents - reduce initialization noise but keep operational info
    "a2a_server.sample_agents.perplexity_agent": "WARNING",
    "a2a_server.sample_agents.time_agent": "WARNING", 
    "a2a_server.sample_agents.weather_agent": "WARNING",
}

# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def configure_logging(
    *,
    level_name: str = "info",
    file_path: Optional[str] = None,
    verbose_modules: Optional[List[str]] = None,
    quiet_modules: Optional[Dict[str, str]] = None,
    json: bool | None = None,
) -> None:
    """Set up root logging & common module levels.

    Parameters
    ----------
    level_name : str
        Global minimum severity (``debug``, ``info`` …).
    file_path : str | None
        If given, duplicate logs to this file.
    verbose_modules : list[str]
        Force DEBUG level for these module names.
    quiet_modules : dict[str, str]
        Map of *module → level* overriding the defaults.
    json : bool | None
        ``True`` → force JSON format, ``False`` → force text. ``None`` obeys
        ``$LOG_FORMAT`` env var (defaults to text).
    """

    # ── Global level --------------------------------------------------------
    root_level = getattr(logging, level_name.upper(), logging.INFO)

    # ── Choose formatter ----------------------------------------------------
    want_json = json if json is not None else os.getenv("LOG_FORMAT") == "json"
    if want_json and _JsonFormatter is not None:
        formatter: logging.Formatter = _JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # ── Handlers ------------------------------------------------------------
    handlers: list[logging.Handler] = []

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(root_level)
    console.setFormatter(formatter)
    handlers.append(console)

    if file_path:
        file_handler = logging.FileHandler(file_path)
        file_handler.setLevel(root_level)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # ── Root logger ---------------------------------------------------------
    root_logger = logging.getLogger()
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    root_logger.setLevel(root_level)
    for h in handlers:
        root_logger.addHandler(h)

    # ── Module-level overrides --------------------------------------------
    if verbose_modules:
        for mod_name in verbose_modules:
            logging.getLogger(mod_name).setLevel(logging.DEBUG)

    merged_quiet = {**_DEFAULT_QUIET_MODULES, **(quiet_modules or {})}
    for mod_name, lvl in merged_quiet.items():
        level_val = getattr(logging, lvl.upper(), None)
        if level_val is not None:
            logging.getLogger(mod_name).setLevel(level_val)