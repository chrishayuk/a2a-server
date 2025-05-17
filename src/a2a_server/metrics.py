# a2a_server/metrics.py
"""
Minimal OpenTelemetry metrics helper for A2A-server
===================================================

✔ Counter   ``http.server.request.count``   (unit = 1)
✔ Histogram ``http.server.request.duration`` (unit = seconds)

Environment
-----------
OTEL_EXPORTER_OTLP_ENDPOINT   – URL of your collector (push mode)
PROMETHEUS_METRICS            – “true” enables /metrics pull endpoint
OTEL_EXPORT_INTERVAL_MS       – export cadence (default 15000 ms)
OTEL_SERVICE_NAME             – resource attr ``service.name``
"""

from __future__ import annotations

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

# ── Prometheus pull exporter (optional) ────────────────────────────────────
_PROM_ENABLED = os.getenv("PROMETHEUS_METRICS", "false").lower() == "true"
prometheus_client = None
_prom_reader = None

if _PROM_ENABLED:
    try:
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        import prometheus_client as _pc

        prometheus_client = _pc
        _prom_reader = PrometheusMetricReader()  # auto-registers in global REGISTRY
    except ModuleNotFoundError:
        # dependency missing → silently disable pull endpoint
        _PROM_ENABLED = False

# ── general config ────────────────────────────────────────────────────────
_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "a2a-server")
_INTERVAL_MS = int(os.getenv("OTEL_EXPORT_INTERVAL_MS", "15000"))

# ── globals (shared between reloads in tests) ─────────────────────────────
_provider: MeterProvider | None = None
_counter: Any | None = None
_histogram: Any | None = None


# ------------------------------------------------------------------------#
# internal helpers                                                        #
# ------------------------------------------------------------------------#
def _init_provider() -> None:
    """Create (or reuse) MeterProvider and instruments.  Idempotent."""
    global _provider, _counter, _histogram  # noqa: PLW0603

    # If someone already configured a provider (e.g. in previous test import)
    # just reuse it – OpenTelemetry forbids overriding the global provider.
    if _provider is None:
        current = metrics.get_meter_provider()
        _provider = current if isinstance(current, MeterProvider) else None

    if _provider and _counter and _histogram:
        return  # already initialised

    readers: list[Any] = []

    # OTLP push (if endpoint configured)
    if _OTLP_ENDPOINT:
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=_OTLP_ENDPOINT, insecure=True),
                export_interval_millis=_INTERVAL_MS,
            )
        )
    else:  # console exporter so you *see* metrics even without OTLP
        readers.append(
            PeriodicExportingMetricReader(
                ConsoleMetricExporter(),
                export_interval_millis=_INTERVAL_MS,
            )
        )

    # Prometheus pull
    if _PROM_ENABLED and _prom_reader is not None:
        readers.append(_prom_reader)

    if _provider is None:  # first time ever → create provider
        _provider = MeterProvider(
            resource=Resource({SERVICE_NAME: _SERVICE_NAME}),
            metric_readers=readers,
        )
        metrics.set_meter_provider(_provider)
    else:  # provider already exists → just add our readers to it
        for r in readers:
            _provider._sdk_config.metric_readers.append(r)  # type: ignore[attr-defined,protected]

    meter = metrics.get_meter("a2a-server", "1.0.0")
    _counter = meter.create_counter(
        "http.server.request.count",
        unit="1",
        description="HTTP requests",
    )
    _histogram = meter.create_histogram(
        "http.server.request.duration",
        unit="s",
        description="Request latency",
    )


# ------------------------------------------------------------------------#
# public API                                                              #
# ------------------------------------------------------------------------#
def instrument_app(app: FastAPI) -> None:  # noqa: D401 – imperative style
    """Attach OTel middleware and (optionally) /metrics route.  Idempotent."""
    _init_provider()

    # ── request/response middleware ───────────────────────────────────────
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
            _counter.add(1, attrs)             # type: ignore[arg-type]
            _histogram.record(duration, attrs)  # type: ignore[arg-type]
            return response

        app.state._otel_middleware = True

    # ── /metrics endpoint (Prometheus) ────────────────────────────────────
    if _PROM_ENABLED and not getattr(app.state, "_prom_endpoint", False):

        from prometheus_client import (
            REGISTRY as _PROM_REGISTRY,
            CONTENT_TYPE_LATEST,
            generate_latest,
        )

        @app.get("/metrics", include_in_schema=False)
        async def _metrics():  # noqa: D401 – HTTP handler
            content = generate_latest(_PROM_REGISTRY)
            return PlainTextResponse(content, media_type=CONTENT_TYPE_LATEST)

        app.state._prom_endpoint = True


def _shutdown_provider() -> None:  # pragma: no cover
    p = globals().get("_provider")
    if p is not None:
        try:
            p.shutdown()
        except Exception:  # noqa: BLE001 – best-effort
            pass


atexit.register(_shutdown_provider)
