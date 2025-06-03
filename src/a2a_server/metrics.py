# a2a_server/metrics.py
from __future__ import annotations
"""Minimal OpenTelemetry metrics helper for A2A-server - now completely quiet
on repeated shutdowns (no more "shutdown can only be called once")."""

import atexit
import os
import time
from typing import Any

from fastapi import FastAPI, Request
from starlette.responses import PlainTextResponse

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

# ---------------------------------------------------------------------------
# Environment flags
# ---------------------------------------------------------------------------

_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
_PROM_ENABLED = os.getenv("PROMETHEUS_METRICS", "false").lower() == "true"
_CONSOLE_ENABLED = os.getenv("CONSOLE_METRICS", "false").lower() == "true"
_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "a2a-server")
_INTERVAL_MS = int(os.getenv("OTEL_EXPORT_INTERVAL_MS", "15000"))

prometheus_client = None
_prom_reader = None
if _PROM_ENABLED:
    try:
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        import prometheus_client as _pc

        prometheus_client = _pc
        _prom_reader = PrometheusMetricReader()  # auto-registers on global REGISTRY
    except ModuleNotFoundError:
        _PROM_ENABLED = False  # dependency unavailable - silently disable

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

_provider: MeterProvider | None = None
_counter: Any | None = None
_histogram: Any | None = None

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _init_provider() -> None:
    """Create (or reuse) the global MeterProvider.  Idempotent."""
    global _provider, _counter, _histogram  # noqa: PLW0603 - module-level singletons

    if _provider is None:
        current = metrics.get_meter_provider()
        _provider = current if isinstance(current, MeterProvider) else None

    if _provider and _counter and _histogram:
        return  # already configured

    readers: list[Any] = []

    # OTLP push (highest priority - if set we always push)
    if _OTLP_ENDPOINT:
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=_OTLP_ENDPOINT, insecure=True),
                export_interval_millis=_INTERVAL_MS,
            )
        )
    elif _CONSOLE_ENABLED:
        readers.append(
            PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=_INTERVAL_MS)
        )

    # Prometheus pull
    if _PROM_ENABLED and _prom_reader is not None:
        readers.append(_prom_reader)

    if _provider is None:
        _provider = MeterProvider(resource=Resource({SERVICE_NAME: _SERVICE_NAME}), metric_readers=readers)
        metrics.set_meter_provider(_provider)
    else:
        for r in readers:
            _provider._sdk_config.metric_readers.append(r)  # type: ignore[attr-defined,protected]

    meter = metrics.get_meter("a2a-server", "1.0.0")
    _counter = meter.create_counter("http.server.request.count", unit="1", description="HTTP requests")
    _histogram = meter.create_histogram("http.server.request.duration", unit="s", description="Request latency")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def instrument_app(app: FastAPI) -> None:  # noqa: D401 - imperative style
    """Attach OTel middleware and (optionally) a /metrics endpoint.  Idempotent."""
    _init_provider()

    # ── request middleware ────────────────────────────────────────────
    if not getattr(app.state, "_otel_middleware", False):

        @app.middleware("http")
        async def _otel_mw(request: Request, call_next):  # type: ignore[override]
            start = time.perf_counter()
            response = await call_next(request)
            duration = time.perf_counter() - start

            route = request.scope.get("route")
            templ = getattr(route, "path", request.url.path)

            attrs = {
                "http.method": request.method,
                "http.route": templ,
                "http.status_code": str(response.status_code),
            }
            _counter.add(1, attrs)  # type: ignore[arg-type]
            _histogram.record(duration, attrs)  # type: ignore[arg-type]
            return response

        app.state._otel_middleware = True

    # ── /metrics endpoint (Prometheus) ────────────────────────────────
    if _PROM_ENABLED and not getattr(app.state, "_prom_endpoint", False):
        from prometheus_client import REGISTRY as _REG, CONTENT_TYPE_LATEST, generate_latest

        @app.get("/metrics", include_in_schema=False)
        async def _metrics():  # noqa: D401
            return PlainTextResponse(generate_latest(_REG), media_type=CONTENT_TYPE_LATEST)

        app.state._prom_endpoint = True

# ---------------------------------------------------------------------------
# Clean-up
# ---------------------------------------------------------------------------

def _shutdown_provider() -> None:  # pragma: no cover - best-effort
    """Idempotent shutdown that stays silent on repeat calls."""
    global _provider  # noqa: PLW0603

    p: MeterProvider | None = _provider
    if p is None:
        return  # already shut down

    # OpenTelemetry marks the provider after first shutdown; respect that flag
    _already = getattr(p, "_shutdown", False) or getattr(p, "_is_shutdown", False)
    if _already:
        _provider = None
        return

    try:
        p.shutdown()
    except Exception:  # noqa: BLE001 - ignore transport errors during exit
        pass
    finally:
        _provider = None  # ensure subsequent calls are no-ops
        # Try a debug log only if stderr is still open
        try:
            import logging
            logging.getLogger(__name__).debug("OpenTelemetry metrics provider shut down (once)")
        except ValueError:
            pass

# register at import time so normal app startup attaches it *once*
aexit = atexit.register
atexit.register(_shutdown_provider)