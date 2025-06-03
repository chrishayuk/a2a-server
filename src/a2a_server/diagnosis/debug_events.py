# File: a2a_server/diagnosis/debug_events.py
"""
Low-level flow-diagnostics helpers for A2A.

🔒  **Opt-out flag**
--------------------
Set ``A2A_DISABLE_DEBUG_EVENTS=1`` **before** the server starts to **skip**
all monkey-patching and verbose logging.  This keeps the import side-effects
predictable in production and aligns with the other “private” modules
(session-routes, debug-routes, …).

These helpers are **only** wired in when
``create_app(..., enable_flow_diagnosis=True)`` is used *and* the flag is **not**
set, so production builds remain unaffected by default.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from functools import wraps
from typing import Any

from fastapi.encoders import jsonable_encoder

# --------------------------------------------------------------------------- #
# Global configuration & opt-out                                              #
# --------------------------------------------------------------------------- #

_DISABLE_ENV = "A2A_DISABLE_DEBUG_EVENTS"
if os.getenv(_DISABLE_ENV):
    # Short-circuit - export NO-OP stubs so the rest of the codebase can import
    # these symbols without conditional checks.
    logging.getLogger(__name__).info("Debug-events disabled via %s", _DISABLE_ENV)

    def add_event_tracing(event_bus):  # type: ignore[override]
        return event_bus

    def trace_task_manager(task_manager):  # type: ignore[override]
        return task_manager

    def trace_handler_methods(handler):  # type: ignore[override]
        return handler

    def verify_handlers(task_manager):  # type: ignore[override]
        return task_manager

    def enable_debug() -> None:  # noqa: D401
        pass

    # Nothing else is executed
    raise SystemExit  # noqa: E701 pragma: no cover

# --------------------------------------------------------------------------- #
# Verbose logger setup                                                        #
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

for name in (
    "a2a_server.pubsub",
    "a2a_server.tasks.task_manager",
    "a2a_server.transport.sse",
    "a2a_server.transport.http",
    "a2a_server.tasks.handlers.google_adk_handler",
    "a2a_server.tasks.handlers.adk_agent_adapter",
):
    logging.getLogger(name).setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Event-bus instrumentation                                                   #
# --------------------------------------------------------------------------- #


def add_event_tracing(event_bus):  # noqa: D401
    """Monkey-patch *event_bus* so every publish / subscribe is logged."""

    orig_publish = event_bus.publish
    orig_subscribe = event_bus.subscribe

    @wraps(orig_publish)
    async def traced_publish(event: Any):  # type: ignore[override]
        try:
            payload = jsonable_encoder(event, exclude_none=True)
            logger.debug("Publishing %s:\n%s", type(event).__name__, json.dumps(payload, indent=2))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to encode event for tracing: %s", exc)

        await orig_publish(event)

    @wraps(orig_subscribe)
    def traced_subscribe():  # type: ignore[override]
        queue = orig_subscribe()
        logger.debug("New EventBus subscription (total=%d)", len(event_bus._queues))
        return queue

    event_bus.publish = traced_publish
    event_bus.subscribe = traced_subscribe
    logger.info("EventBus instrumentation enabled")
    return event_bus


# --------------------------------------------------------------------------- #
# Task-manager instrumentation                                                #
# --------------------------------------------------------------------------- #


def trace_task_manager(task_manager):  # noqa: D401
    """Patch :pyclass:`TaskManager` so `create_task` emits debug lines."""

    orig_create_task = task_manager.create_task

    @wraps(orig_create_task)
    async def traced_create_task(*args, **kwargs):  # type: ignore[override]
        handler = kwargs.get("handler_name") or kwargs.get("handler")
        logger.debug("Creating task (handler=%s)", handler)
        task = await orig_create_task(*args, **kwargs)
        logger.debug("Task created (id=%s)", task.id)
        return task

    task_manager.create_task = traced_create_task
    logger.info("TaskManager instrumentation enabled")
    return task_manager


# --------------------------------------------------------------------------- #
# Handler instrumentation                                                     #
# --------------------------------------------------------------------------- #


def trace_handler_methods(handler):  # noqa: D401
    """Wrap the async generator `process_task` to log every yield."""

    orig_process_task = handler.process_task

    @wraps(orig_process_task)
    async def traced_process_task(task_id, message, session_id=None):  # noqa: D401
        hlog = logging.getLogger(f"a2a_server.tasks.handlers.{handler.name}")
        hlog.debug("Processing task %s", task_id)

        async for event in orig_process_task(task_id, message, session_id):
            hlog.debug("Yielded %s for %s", type(event).__name__, task_id)
            yield event

        hlog.debug("Completed task %s", task_id)

    handler.process_task = traced_process_task
    return handler


# --------------------------------------------------------------------------- #
# Convenience helpers                                                         #
# --------------------------------------------------------------------------- #


def verify_handlers(task_manager):  # noqa: D401
    """Log a summary of registered handlers and patch them for tracing."""
    logger.info("Registered handlers: %s", task_manager.get_handlers())
    logger.info("Default handler: %s", task_manager.get_default_handler())

    for name in task_manager.get_handlers():
        try:
            trace_handler_methods(task_manager.get_handler(name))
            logger.debug("Tracing enabled for handler '%s'", name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to patch handler '%s': %s", name, exc)

    return task_manager


def enable_debug() -> None:  # noqa: D401
    """Convenience shim to switch on coarse global debug flags."""
    os.environ.setdefault("DEBUG_A2A", "1")
    os.environ.setdefault("DEBUG_LEVEL", "DEBUG")
    logger.info("DEBUG_A2A environment vars set")
