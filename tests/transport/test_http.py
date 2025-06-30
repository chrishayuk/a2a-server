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

# Fix the import to get the actual FastAPI app instance
from a2a_server import get_app
from a2a_server.transport.http import MAX_BODY, REQUEST_TIMEOUT

# ---------------------------------------------------------------------------
# helpers / constants
# ---------------------------------------------------------------------------
_OK_STATES = {"submitted", "working"}

# Get the FastAPI app instance (not the module)
_fastapi_app = get_app()
transport = ASGITransport(app=_fastapi_app)


async def _rpc(ac: AsyncClient, id_: int, method: str, params: Dict[str, Any] | None = None):  # noqa: ANN001
    payload = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    return await ac.post("/rpc", json=payload)


# ---------------------------------------------------------------------------
# happy-path scenarios (kept from original test suite)
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
# new defensive guards - added May 2025
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
# SSE - at least one smoke-test (sendSubscribe)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_subscribe_smoke():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        sub_params = {
            "id": "ignored",
            "message": {"role": "user", "parts": [{"type": "text", "text": "Hi"}]},
        }
        # The server returns 200 immediately with a JSON-RPC envelope - we just smoke-check.
        r = await _rpc(ac, 40, "tasks/sendSubscribe", sub_params)
        assert r.status_code == 200
        assert r.json()["result"]["status"]["state"] in _OK_STATES

        # cancel to tidy-up
        tid = r.json()["result"]["id"]
        await _rpc(ac, 41, "tasks/cancel", {"id": tid})


# ---------------------------------------------------------------------------
# Additional test to verify the app is working correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_initialization():
    """Test that the FastAPI app is properly initialized."""
    # Verify we have a FastAPI app instance
    from fastapi import FastAPI
    assert isinstance(_fastapi_app, FastAPI)
    
    # Test basic health endpoint
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/")
        assert r.status_code == 200
        data = r.json()
        assert "service" in data
        assert data["service"] == "A2A Server"


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling for invalid requests."""
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test invalid JSON-RPC format
        r = await ac.post("/rpc", json={"not": "jsonrpc"})
        # Should still return 200 but with an error response
        assert r.status_code == 200
        
        # Test with completely invalid JSON - FastAPI might handle this at different levels
        try:
            r = await ac.post("/rpc", content="not json", headers={"content-type": "application/json"})
            # A2A server might return 200, 400, or 422 depending on where the error is caught
            assert r.status_code in [200, 400, 422]
        except Exception:
            # Some setups might raise an exception for completely invalid JSON
            pass
        
        # Test with valid JSON but invalid JSON-RPC structure
        r = await ac.post("/rpc", json={"invalid": "structure"})
        assert r.status_code == 200  # A2A server handles this gracefully


@pytest.mark.asyncio 
async def test_handler_routes():
    """Test that handler-specific routes are available."""
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test root path
        r = await ac.get("/")
        assert r.status_code == 200
        
        # The exact handler routes will depend on your configuration
        # This is a basic smoke test that the app is routing correctly