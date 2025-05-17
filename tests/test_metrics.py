# File: tests/test_metrics.py
"""
Unit-tests for the metrics helper.

*   Ensures that the Console exporter is invoked when no OTLP endpoint
    is configured.
*   Verifies that calling `instrument_app()` twice is a no-op
    (middleware not duplicated, flag set).
"""

from __future__ import annotations

import importlib
import types
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helper to reload metrics with a pristine module-state
# ---------------------------------------------------------------------------

def _reload_metrics(monkeypatch) -> types.ModuleType:  # noqa: ANN001
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    # remove from sys.modules so we get a clean import (fresh globals)
    importlib.sys.modules.pop("a2a_server.metrics", None)
    return importlib.import_module("a2a_server.metrics")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_console_exporter_called(monkeypatch):
    metrics_mod = _reload_metrics(monkeypatch)
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        MetricExportResult,
    )

    calls: List[Any] = []

    # monkey-patch ConsoleMetricExporter.export so we can spy on calls
    def _fake_export(self, batch, *args, **kwargs):  # noqa: ANN001
        calls.append(batch)
        return MetricExportResult.SUCCESS

    monkeypatch.setattr(ConsoleMetricExporter, "export", _fake_export, raising=True)

    # FastAPI + instrumentation
    app = FastAPI()

    @app.get("/hello")
    async def _hello():  # noqa: D401 - dummy route
        return {"ok": True}

    metrics_mod.instrument_app(app)
    client = TestClient(app)

    # generate a couple of requests
    client.get("/hello")
    client.get("/hello")

    # force an on-demand export so our patched exporter is triggered
    metrics_mod._provider.force_flush()  # type: ignore[attr-defined]

    assert calls, "ConsoleMetricExporter.export was not invoked"


def test_instrument_app_idempotent(monkeypatch):
    metrics_mod = _reload_metrics(monkeypatch)
    app = FastAPI()

    metrics_mod.instrument_app(app)
    first_len = len(app.user_middleware)

    # second call must *not* add another middleware instance
    metrics_mod.instrument_app(app)
    second_len = len(app.user_middleware)

    assert first_len == second_len
    assert getattr(app.state, "_otel_middleware", False)
