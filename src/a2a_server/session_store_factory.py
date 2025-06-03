#!/usr/bin/env python3
# a2a_server/session_store_factory.py
"""
Factory for chuk-session-manager stores.

The first call to :func:`build_session_store` instantiates **one** global
store instance and re-uses it for the lifetime of the process.

Environment variables
---------------------
A2A_SESSION_BACKEND   "memory" (default) | "redis"
A2A_REDIS_URL         Redis DSN if the backend is *redis*
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ── module-level singletons ───────────────────────────────────────────────
_STORE: Optional[object] = None
_BACKEND_ENV = "A2A_SESSION_BACKEND"
_REDIS_URL_ENV = "A2A_REDIS_URL"

# ── helpers ───────────────────────────────────────────────────────────────
def _memory_store():
    mod = importlib.import_module("chuk_session_manager.storage.providers.memory")
    return mod.InMemorySessionStore()                   # type: ignore[attr-defined]

def _redis_store():
    try:
        mod = importlib.import_module("chuk_session_manager.storage.providers.redis")
    except ModuleNotFoundError as exc:                  # noqa: BLE001
        logger.warning(
            "Redis backend requested but redis provider not installed - "
            "falling back to in-memory store (%s)", exc
        )
        return _memory_store()

    redis_url = os.getenv(_REDIS_URL_ENV, "redis://localhost:6379/0")
    logger.info("Creating RedisSessionStore (%s)", redis_url)
    return mod.RedisSessionStore(redis_url=redis_url)   # type: ignore[attr-defined]

# ── public API ────────────────────────────────────────────────────────────
def build_session_store(*, refresh: bool = False):
    """
    Build (or return cached) session store selected purely via env-vars.

    Parameters
    ----------
    refresh
        Force creation of a **new** store even if one is already cached.
    """
    global _STORE                                       # pylint: disable=global-statement
    if _STORE is not None and not refresh:
        return _STORE

    backend = os.getenv(_BACKEND_ENV, "memory").lower()
    _STORE = _redis_store() if backend == "redis" else _memory_store()

    logger.info("Using %s session store", _STORE.__class__.__name__)
    return _STORE

__all__ = ["build_session_store"]
