import pytest
from httpx import AsyncClient, ASGITransport

from a2a_server import app

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

# --- Additional HTTP transport tests ---

@pytest.mark.asyncio
async def test_handler_specific_rpc():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Send via specific handler endpoint (/echo/rpc)
        send_payload = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tasks/send",
            "params": {
                "id": "ignored",
                "sessionId": None,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Hello Echo"}]
                }
            }
        }
        send_resp = await ac.post("/echo/rpc", json=send_payload)
        assert send_resp.status_code == 200
        data = send_resp.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 20
        result = data["result"]
        # EchoHandler should echo the input text
        # Here we verify the task is created under "echo"
        assert result["status"]["state"] == "submitted"
        assert result["id"]

@pytest.mark.asyncio
async def test_rpc_get_nonexistent_task():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Attempt to get a task ID that doesn't exist
        fake_id = "00000000-0000-0000-0000-000000000000"
        get_payload = {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tasks/get",
            "params": {"id": fake_id}
        }
        resp = await ac.post("/rpc", json=get_payload)
        assert resp.status_code == 200
        error = resp.json().get("error")
        # Expect a JSON-RPC error for TaskNotFound
        assert error is not None
        assert "TaskNotFound" in error.get("message", "")

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
                    "parts": [{"type": "text", "text": "Subscribe me"}]
                }
            }
        }
        sub_resp = await ac.post("/rpc", json=sub_payload)
        assert sub_resp.status_code == 200
        data = sub_resp.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 40
        assert "result" in data
        res = data["result"]
        assert res["status"]["state"] == "submitted"
        # Clean up: cancel the subscribed task
        task_id = res["id"]
        cancel_payload = {"jsonrpc": "2.0", "id": 41, "method": "tasks/cancel", "params": {"id": task_id}}
        await ac.post("/rpc", json=cancel_payload)