# File: src/a2a_server/transport/stdio.py

"""
Stdio transport for server JSON-RPC: processes one message (line) at a time.
"""
import json
from typing import Optional
from a2a_json_rpc.protocol import JSONRPCProtocol
from fastapi.encoders import jsonable_encoder

__all__ = ["handle_stdio_message"]


def handle_stdio_message(
    protocol: JSONRPCProtocol,
    raw: str
) -> Optional[str]:
    """
    Process a single JSON-RPC message (newline-terminated) from stdin and return
    a JSON-encoded response string, or None if it's a notification or invalid JSON.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Ignore invalid JSON
        return None

    # If no ID provided or id is None, treat as notification (ignore)
    if payload.get("id") is None:
        return None

    # Dispatch: get the raw response dict
    response = protocol.handle_raw(payload)
    if response is None:
        return None

    # Serialize any enums or Pydantic models into JSON-serializable types
    serializable = jsonable_encoder(response)
    # Return the serialized JSON-RPC response
    return json.dumps(serializable)
