# tests/test_run.py
# tests/cli/test_run.py
"""
Unit-tests for the async-native CLI entry-point in a2a_server.__main__
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

import a2a_server.__main__ as entry


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


class _DummyArgs(argparse.Namespace):
    """Mimic the object returned by a2a_server.arguments.parse_args()."""

    # handler / discovery switches
    config: str = "agent.yaml"
    handler_packages: list[str] | None = None
    no_discovery: bool = False
    enable_flow_diagnosis: bool = False

    # misc CLI flags
    log_level: str | None = "WARNING"
    list_routes: bool = False


@pytest.fixture(autouse=True)
def _quiet_uvicorn(caplog: pytest.LogCaptureFixture):
    """Silence Uvicorn banner during tests."""
    caplog.set_level(logging.CRITICAL, logger="uvicorn.error")


# ---------------------------------------------------------------------------
# _build_app
# ---------------------------------------------------------------------------


def test_build_app_returns_fastapi():
    """_build_app should return a working FastAPI instance."""
    cfg = {
        "handlers": {
            "use_discovery": False,
            "handler_packages": [],
            "handler_order": ["echo"],
        },
        "logging": {"level": "WARNING"},
        "server": {},
    }

    app = entry._build_app(cfg, _DummyArgs())  # type: ignore[arg-type]
    assert isinstance(app, FastAPI)

    client = httpx.AsyncClient(app=app, base_url="http://test")
    try:
        resp = asyncio.run(client.get("/"))
        assert resp.status_code == 200
    finally:
        asyncio.run(client.aclose())


# ---------------------------------------------------------------------------
# _serve  (monkey-patch Uvicorn so no real sockets are opened)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_starts_and_stops_quickly():
    """_serve should honour `should_exit` and shut down promptly."""
    app = FastAPI()

    async def _fake_serve(self):  # noqa: D401 – stub
        while not self.should_exit:
            await asyncio.sleep(0)  # yield control

    with patch("uvicorn.Server.serve", new=_fake_serve):
        task = asyncio.create_task(
            entry._serve(app, host="127.0.0.1", port=0, log_level="warning")
        )

        await asyncio.sleep(0)          # let it start
        assert not task.done()

        # emulate Ctrl-C by flipping the flag used inside _serve
        task.get_coro().cr_frame.f_locals["server"].should_exit = True

        await asyncio.wait_for(task, timeout=0.25)
