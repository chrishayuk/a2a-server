# tests/server/transport/test_http.py
import pytest
from httpx import AsyncClient, ASGITransport

from a2a.server import app

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
                }
            }
        }
        send_resp = await ac.post("/rpc", json=send_payload)
        assert send_resp.status_code == 200
        data = send_resp.json()
        # Validate JSON-RPC envelope
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "result" in data
        result = data["result"]
        # Task fields
        assert isinstance(result["id"], str)
        assert isinstance(result["sessionId"], str)
        assert result["status"]["state"] == "submitted"
        history = result.get("history")
        assert isinstance(history, list) and len(history) == 1
        msg = history[0]
        assert msg["role"] == "user"
        parts = msg.get("parts")
        assert isinstance(parts, list)
        assert parts[0]["type"] == "text"
        assert parts[0]["text"] == "Hello"

        # 2) Get the same task by ID
        task_id = result["id"]
        get_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tasks/get",
            "params": {"id": task_id}
        }
        get_resp = await ac.post("/rpc", json=get_payload)
        assert get_resp.status_code == 200
        data2 = get_resp.json()
        assert data2["jsonrpc"] == "2.0"
        assert data2["id"] == 2
        result2 = data2["result"]
        assert result2["id"] == task_id
        assert result2["status"]["state"] == "submitted"

@pytest.mark.asyncio
async def test_rpc_cancel_task():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create a task to cancel
        send_payload = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tasks/send",
            "params": {
                "id": "ignored",
                "sessionId": None,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Cancel me"}]
                }
            }
        }
        send_resp = await ac.post("/rpc", json=send_payload)
        task_id = send_resp.json()["result"]["id"]

        # Cancel the task
        cancel_payload = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tasks/cancel",
            "params": {"id": task_id}
        }
        cancel_resp = await ac.post("/rpc", json=cancel_payload)
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 11
        assert data.get("result") is None

        # Verify canceled status
        get_payload = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tasks/get",
            "params": {"id": task_id}
        }
        get_resp = await ac.post("/rpc", json=get_payload)
        status = get_resp.json()["result"]["status"]["state"]
        assert status == "canceled"
