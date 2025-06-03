#!/usr/bin/env python3
# a2a_server/diagnosis/flow_diagnosis.py
"""
End-to-end flow-diagnostics helpers for the A2A server.

🔒  Opt-out
-----------
Set **A2A_DISABLE_FLOW_DIAGNOSIS=1** before startup to turn every tracer into
a no-op.  This mirrors `diagnosis/debug_events.py`, giving operators a single
switch to disable “heavy” tracing in production.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import wraps
from typing import Any, Callable, Coroutine, Optional

from fastapi.encoders import jsonable_encoder

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------#
# Opt-out support                                                            #
# ---------------------------------------------------------------------------#

_DISABLE_ENV = "A2A_DISABLE_FLOW_DIAGNOSIS"
if os.getenv(_DISABLE_ENV):
    logger.info("Flow-diagnosis disabled via %s", _DISABLE_ENV)

    # Harmless stubs so importers never crash
    def trace_http_transport(f):           # type: ignore[override]
        return f

    def trace_sse_transport(f):            # type: ignore[override]
        return f

    def trace_event_bus(event_bus):        # type: ignore[override]
        async def _noop_monitor():         # noqa: D401
            return None
        return _noop_monitor

    def apply_flow_tracing(               # type: ignore[override]
        app_module=None,
        http_module=None,
        sse_module=None,
        event_bus=None,
    ):
        """No-op when flow diagnostics are disabled."""
        return None

else:
    # -----------------------------------------------------------------------#
    # Helpers                                                                #
    # -----------------------------------------------------------------------#

    def _safe_json(obj: Any) -> str:
        """Encode *obj* to pretty JSON, swallowing errors."""
        try:
            return json.dumps(jsonable_encoder(obj, exclude_none=True), indent=2)
        except Exception:  # noqa: BLE001
            return "<unserialisable>"

    # -----------------------------------------------------------------------#
    # HTTP transport tracer                                                  #
    # -----------------------------------------------------------------------#

    def trace_http_transport(setup_http_func: Callable):  # noqa: D401
        """Wrap ``setup_http`` so every subscription / publish is logged."""

        original_setup = setup_http_func

        def traced_setup_http(app, protocol, task_manager, event_bus=None):  # noqa: D401
            logger.info("Installing HTTP transport tracer")

            @app.get("/debug/event-flow", include_in_schema=False)
            async def debug_event_flow():  # noqa: D401
                return {
                    "status": "ok",
                    "components": {
                        "event_bus": {
                            "type": type(event_bus).__name__,
                            "subscriptions": len(getattr(event_bus, "_queues", [])),
                        },
                        "task_manager": {
                            "type": type(task_manager).__name__,
                            "handlers": list(task_manager.get_handlers().keys()),
                            "default_handler": task_manager.get_default_handler(),
                            "active_tasks": len(getattr(task_manager, "_tasks", {})),
                        },
                        "protocol": {
                            "type": type(protocol).__name__,
                            "methods": list(getattr(protocol, "_methods", {}).keys()),
                        },
                    },
                }

            # Patch low-level streaming handler (best-effort)
            module_name = setup_http_func.__module__
            try:
                module = __import__(module_name, fromlist=["handle_sendsubscribe_streaming"])
                if hasattr(module, "handle_sendsubscribe_streaming"):
                    original_handler = module.handle_sendsubscribe_streaming

                    async def traced_handler(*args, **kwargs):  # type: ignore[override]
                        logger.debug("handle_sendsubscribe_streaming → start")
                        try:
                            result = await original_handler(*args, **kwargs)
                            logger.debug("handle_sendsubscribe_streaming → %s", type(result).__name__)
                            return result
                        except Exception as exc:  # noqa: BLE001
                            logger.error("handle_sendsubscribe_streaming failed: %s", exc, exc_info=True)
                            raise

                    module.handle_sendsubscribe_streaming = traced_handler
                    logger.info("Patched handle_sendsubscribe_streaming")
            except Exception:  # noqa: BLE001
                pass  # ignore if unavailable

            return original_setup(app, protocol, task_manager, event_bus)

        return traced_setup_http

    # -----------------------------------------------------------------------#
    # SSE transport tracer                                                   #
    # -----------------------------------------------------------------------#

    def trace_sse_transport(setup_sse_func: Callable):  # noqa: D401
        """Wrap ``setup_sse`` to log subscription and event flow."""

        original_setup = setup_sse_func

        def traced_setup_sse(app, event_bus, task_manager):  # noqa: D401
            logger.info("Installing SSE transport tracer")

            module_name = setup_sse_func.__module__
            try:
                module = __import__(module_name, fromlist=["_create_sse_response"])
                if hasattr(module, "_create_sse_response"):
                    original_creator = module._create_sse_response

                    async def traced_creator(event_bus, task_ids=None):  # noqa: D401
                        logger.debug("Creating SSE response (tasks=%s)", task_ids)

                        # Wrap subscribe
                        original_subscribe = event_bus.subscribe

                        def traced_subscribe():
                            logger.debug("SSE → subscribe()")
                            queue = original_subscribe()
                            logger.debug("SSE subscription created (total=%d)", len(event_bus._queues))

                            original_get = queue.get

                            async def traced_get():
                                evt = await original_get()
                                logger.debug(
                                    "SSE received %s for task %s",
                                    type(evt).__name__,
                                    getattr(evt, 'id', None),
                                )
                                return evt

                            queue.get = traced_get  # type: ignore[assignment]
                            return queue

                        event_bus.subscribe = traced_subscribe
                        try:
                            resp = await original_creator(event_bus, task_ids)
                            logger.debug("SSE response ready (media_type=%s)", resp.media_type)
                            return resp
                        finally:
                            event_bus.subscribe = original_subscribe

                    module._create_sse_response = traced_creator
                    logger.info("Patched _create_sse_response")
            except Exception:  # noqa: BLE001
                pass

            return original_setup(app, event_bus, task_manager)

        return traced_setup_sse

    # -----------------------------------------------------------------------#
    # Event-bus tracer                                                       #
    # -----------------------------------------------------------------------#

    def trace_event_bus(event_bus):  # noqa: D401
        """Patch *event_bus.publish* and return a monitor coroutine."""

        original_publish = event_bus.publish

        async def traced_publish(event):  # type: ignore[override]
            etype = type(event).__name__
            eid = getattr(event, "id", None)
            logger.info("EventBus → publish %s (task=%s)", etype, eid)
            await original_publish(event)
            logger.debug("EventBus → publish COMPLETE (%s)", etype)

        event_bus.publish = traced_publish  # type: ignore[assignment]

        async def monitor_subscriptions():  # noqa: D401
            try:
                while True:
                    count = len(getattr(event_bus, "_queues", []))
                    logger.debug("EventBus subscription count = %d", count)
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("Subscription monitor cancelled - exiting")

        logger.info("EventBus instrumentation enabled")
        return monitor_subscriptions

    # -----------------------------------------------------------------------#
    # Public entry-point                                                     #
    # -----------------------------------------------------------------------#

    def apply_flow_tracing(  # noqa: D401
        app_module=None,
        http_module=None,
        sse_module=None,
        event_bus=None,
    ):
        """
        Patch supplied modules / event_bus in-place and return an **optional
        monitor coroutine**.  Callers (e.g. :func:`create_app`) should schedule
        that coroutine on startup so it can emit periodic stats.
        """
        if http_module and hasattr(http_module, "setup_http"):
            logger.info("Tracing HTTP transport")
            http_module.setup_http = trace_http_transport(http_module.setup_http)

        if sse_module and hasattr(sse_module, "setup_sse"):
            logger.info("Tracing SSE transport")
            sse_module.setup_sse = trace_sse_transport(sse_module.setup_sse)

        monitor_coro: Optional[Callable[[], Coroutine]] = None
        if event_bus:
            logger.info("Tracing EventBus")
            monitor_coro = trace_event_bus(event_bus)

        logger.info("Flow-diagnosis instrumentation applied")
        return monitor_coro
