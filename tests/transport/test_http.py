# tests/transport/test_http.py
"""
Extended HTTP-transport integration tests
=========================================
Covers the original happy-path scenarios **plus** the defensive hardening added
in May-2025 (`MAX_BODY`, param-type check, wall-time timeout).

All tests run against the *real* FastAPI app, mounted through an
`httpx.ASGITransport`, so no real sockets are needed.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
from httpx import ASGITransport, AsyncClient

from a2a_server import app as _fastapi_app
from a2a_server.transport.http import MAX_BODY, REQUEST_TIMEOUT

# ---------------------------------------------------------------------------
# helpers / constants
# ---------------------------------------------------------------------------
_OK_STATES = {"submitted", "working"}
transport = ASGITransport(app=_fastapi_app)


async def _rpc(ac: AsyncClient, id_: int, method: str, params: Dict[str, Any] | None = None):  # noqa: ANN001
    payload = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    return await ac.post("/rpc", json=payload)


# ---------------------------------------------------------------------------
# happy‑path scenarios (kept from original test suite)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rpc_send_and_get():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        send_params = {
            "id": "ignored",
            "sessionId": None,
            "message": {"role": "user", "parts": [{"type": "text", "text": "Hello"}]},
        }
        r1 = await _rpc(ac, 1, "tasks/send", send_params)
        assert r1.status_code == 200
        tid = r1.json()["result"]["id"]

        r2 = await _rpc(ac, 2, "tasks/get", {"id": tid})
        assert r2.status_code == 200
        assert r2.json()["result"]["id"] == tid


@pytest.mark.asyncio
async def test_rpc_cancel_task():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        tid = (
            await _rpc(
                ac,
                10,
                "tasks/send",
                {
                    "id": "ignored",
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Cancel me"}],
                    },
                },
            )
        ).json()["result"]["id"]

        r_cancel = await _rpc(ac, 11, "tasks/cancel", {"id": tid})
        assert r_cancel.status_code == 200

        status = (
            await _rpc(ac, 12, "tasks/get", {"id": tid})
        ).json()["result"]["status"]["state"]
        assert status == "canceled"


@pytest.mark.asyncio
async def test_handler_specific_rpc():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        params = {
            "id": "ignored",
            "message": {"role": "user", "parts": [{"type": "text", "text": "Echo"}]},
        }
        r = await ac.post("/echo/rpc", json={"jsonrpc": "2.0", "id": 20, "method": "tasks/send", "params": params})
        assert r.status_code == 200
        assert r.json()["result"]["status"]["state"] in _OK_STATES


# ---------------------------------------------------------------------------
# new defensive guards - added May 2025
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payload_too_large():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        huge = "x" * (MAX_BODY + 1024)
        params = {
            "id": "ignored",
            "message": {"role": "user", "parts": [{"type": "text", "text": huge}]},
        }
        r = await _rpc(ac, 99, "tasks/send", params)
        assert r.status_code == 413


@pytest.mark.asyncio
async def test_params_not_object():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        bad_payload = {"jsonrpc": "2.0", "id": 55, "method": "tasks/send", "params": "oops"}
        r = await ac.post("/rpc", json=bad_payload)
        assert r.status_code == 422
        assert "params" in r.text.lower()


@pytest.mark.asyncio
async def test_request_timeout(monkeypatch):
    # patch Protocol so every call sleeps longer than the budget
    from a2a_json_rpc.protocol import JSONRPCProtocol

    async def _slow(_self, _payload):  # noqa: D401, ANN001
        await asyncio.sleep(REQUEST_TIMEOUT + 0.5)
        return None  # unreachable but keeps mypy happy

    monkeypatch.setattr(JSONRPCProtocol, "_handle_raw_async", _slow, raising=True)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await _rpc(ac, 77, "tasks/get", {"id": "whatever"})
        assert r.status_code == 504


# ---------------------------------------------------------------------------
# SSE - at least one smoke‑test (sendSubscribe)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_subscribe_smoke():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        sub_params = {
            "id": "ignored",
            "message": {"role": "user", "parts": [{"type": "text", "text": "Hi"}]},
        }
        # The server returns 200 immediately with a JSON‑RPC envelope - we just smoke‑check.
        r = await _rpc(ac, 40, "tasks/sendSubscribe", sub_params)
        assert r.status_code == 200
        assert r.json()["result"]["status"]["state"] in _OK_STATES

        # cancel to tidy‑up
        tid = r.json()["result"]["id"]
        await _rpc(ac, 41, "tasks/cancel", {"id": tid})
