# tests/transport/test_http.py
import pytest
from httpx import AsyncClient, ASGITransport

from a2a_server import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A task can legitimately be in either state immediately after creation,
# depending on how fast the background coroutine starts.
_OK_STATES = {"submitted", "working"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rpc_send_and_get():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1) Send a task
        send_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "id": "ignored",
                "sessionId": None,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Hello"}]
                },
            },
        }
        send_resp = await ac.post("/rpc", json=send_payload)
        assert send_resp.status_code == 200
        data = send_resp.json()

        # JSON-RPC envelope
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        result = data["result"]

        # Basic task fields
        assert isinstance(result["id"], str)
        assert isinstance(result["sessionId"], str)
        assert result["status"]["state"] in _OK_STATES

        # History
        history = result.get("history")
        assert isinstance(history, list) and len(history) == 1
        msg = history[0]
        assert msg["role"] == "user"
        parts = msg["parts"]
        assert parts[0]["type"] == "text"
        assert parts[0]["text"] == "Hello"

        # 2) Get the same task by ID
        task_id = result["id"]
        get_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tasks/get",
            "params": {"id": task_id},
        }
        get_resp = await ac.post("/rpc", json=get_payload)
        assert get_resp.status_code == 200
        data2 = get_resp.json()
        assert data2["jsonrpc"] == "2.0"
        assert data2["id"] == 2
        result2 = data2["result"]
        assert result2["id"] == task_id
        assert result2["status"]["state"] in _OK_STATES


@pytest.mark.asyncio
async def test_rpc_cancel_task():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create a task we will cancel
        send_payload = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tasks/send",
            "params": {
                "id": "ignored",
                "sessionId": None,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Cancel me"}],
                },
            },
        }
        task_id = (await ac.post("/rpc", json=send_payload)).json()["result"]["id"]

        # Cancel
        cancel_payload = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tasks/cancel",
            "params": {"id": task_id},
        }
        cancel_resp = await ac.post("/rpc", json=cancel_payload)
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["id"] == 11

        # Verify canceled
        get_payload = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tasks/get",
            "params": {"id": task_id},
        }
        status = (await ac.post("/rpc", json=get_payload)).json()["result"]["status"][
            "state"
        ]
        assert status == "canceled"


# ---------------------------------------------------------------------------
# Additional HTTP transport cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_specific_rpc():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        send_payload = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tasks/send",
            "params": {
                "id": "ignored",
                "sessionId": None,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Hello Echo"}],
                },
            },
        }
        data = (await ac.post("/echo/rpc", json=send_payload)).json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 20
        assert data["result"]["status"]["state"] in _OK_STATES


@pytest.mark.asyncio
async def test_rpc_get_nonexistent_task():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        fake_id = "00000000-0000-0000-0000-000000000000"
        get_payload = {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tasks/get",
            "params": {"id": fake_id},
        }
        error = (await ac.post("/rpc", json=get_payload)).json().get("error")
        assert error and "TaskNotFound" in error.get("message", "")


@pytest.mark.asyncio
async def test_send_subscribe_method():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        sub_payload = {
            "jsonrpc": "2.0",
            "id": 40,
            "method": "tasks/sendSubscribe",
            "params": {
                "id": "ignored",
                "sessionId": None,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Subscribe me"}],
                },
            },
        }
        res = (await ac.post("/rpc", json=sub_payload)).json()["result"]
        assert res["status"]["state"] in _OK_STATES

        # tidy-up
        await ac.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 41,
                "method": "tasks/cancel",
                "params": {"id": res["id"]},
            },
        )
