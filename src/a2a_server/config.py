# a2a_server/config.py
from __future__ import annotations
"""Asyn-native configuration loader for the A2A server.

This replaces the original *blocking* version with an implementation that
reads YAML using ``aiofiles`` so startup never pauses the event-loop.
"""

import os
from typing import Any, Dict, Optional

import aiofiles
import yaml

# ---------------------------------------------------------------------------
# Default configuration (merged with YAML on disk)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "0.0.0.0",
        "port": 8000,
    },
    "logging": {
        "level": "info",
        "file": None,
        "verbose_modules": [],
        "quiet_modules": {
            "httpx": "ERROR",
            "LiteLLM": "ERROR",
            "google.adk": "ERROR",
        },
    },
    "handlers": {
        "use_discovery": True,
        "handler_packages": ["a2a_server.tasks.handlers"],
        "default_handler": "echo",
    },
}

# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

async def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Return the merged configuration dictionary.

    The coroutine deep-copies :data:`DEFAULT_CONFIG`, then (optionally) loads a
    YAML file and merges it into the copy **recursively**.  Missing file →
    silently ignored; invalid YAML → raised.
    """

    config: Dict[str, Any] = DEFAULT_CONFIG.copy()

    if config_path and os.path.exists(config_path):
        async with aiofiles.open(config_path, "r") as f:
            raw = await f.read()
        user_cfg = yaml.safe_load(raw) or {}
        _deep_update(config, user_cfg)

    return config

# ---------------------------------------------------------------------------
# Internal utils
# ---------------------------------------------------------------------------

def _deep_update(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    """Recursively merge *source* into *target* (in-place)."""

    for key, value in source.items():
        if (
            key in target
            and isinstance(target[key], dict)
            and isinstance(value, dict)
        ):
            _deep_update(target[key], value)
        else:
            target[key] = value
