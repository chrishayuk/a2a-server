# A2A: Agent-to-Agent Communication Server

A lightweight, transport-agnostic framework for agent-to-agent communication based on JSON-RPC.

## Server

The A2A server provides a flexible JSON-RPC interface for agent-to-agent communication with support for multiple transport protocols.

### Features

- **Multiple Transport Protocols**:
  - HTTP JSON-RPC endpoint (`POST /rpc`)
  - WebSocket for bidirectional communication (`/ws`)
  - Server-Sent Events (SSE) for real-time updates (`/events`)
  - Standard I/O mode for CLI applications (`--stdio`)

- **Task-Based Workflow**:
  - Create and manage asynchronous tasks
  - Monitor task status through state transitions
  - Receive artifacts produced during task execution

- **Simple Event System**:
  - Real-time notifications for status changes
  - Artifact update events
  - Event replay for reconnecting clients

- **Extensible Handler System**:
  - Automatic handler discovery
  - Plugin system via entry points (`a2a.task_handlers`)
  - Custom handler development via subclassing `TaskHandler`

### Running the Server

```bash
# Basic usage (HTTP, WS, SSE on port 8000)
uv run a2a-server

# Specify host and port
uv run a2a-server --host 0.0.0.0 --port 8000

# Enable detailed logging
uv run a2a-server --log-level debug

# Run in stdio JSON-RPC mode
uv run a2a-server --stdio

# List all available task handlers
uv run a2a-server --list-handlers

# Register additional handler packages
uv run a2a-server --handler-package my_custom_module.handlers

# Disable automatic handler discovery
uv run a2a-server --no-discovery
```

### Example: Pirate Agent via YAML

You can configure a custom Google ADK–based "pirate" agent entirely in YAML.  
Create `agent.yaml`:

```yaml
server:
  port: 8000

handlers:
  use_discovery: false    # skip built-in echo handler
  default: pirate_agent

  pirate_agent:
    type: a2a.server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: a2a.server.sample_agents.pirate_agent.pirate_agent
    name: pirate_agent
```

Then launch:

```bash
uv run a2a-server --config pirate_agent.yaml --log-level debug
```

The server will register your `pirate_agent` handler as default and stream back playful pirate responses:

```bash
# Create a task
curl -N -X POST http://127.0.0.1:8000/rpc \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tasks/send",
    "params":{
      "id":"task-1234",
      "message":{
        "role":"user",
        "parts":[{ "type":"text","text":"What be yer name, scallywag?" }]
      }
    }
  }'

# Stream events
curl -N http://127.0.0.1:8000/events
```

### Example: Pirate Agent via Python Script

Alternatively, spin up the pirate agent with a self-contained script:

```python
#!/usr/bin/env python3
# examples/google_adk_pirate_agent.py
"""
A2A Google ADK Agent Server Example
"""
import logging
import uvicorn
from a2a.server.app import create_app
from a2a.server.tasks.handlers.google_adk_handler import GoogleADKHandler
from a2a.server.tasks.handlers.adk_agent_adapter import ADKAgentAdapter
from a2a.server.logging import configure_logging
from a2a.server.sample_agents.pirate_agent import pirate_agent as agent

# Constants
HOST = "0.0.0.0"
PORT = 8000

# Configure logging
configure_logging(level_name="info")
logger = logging.getLogger(__name__)


def main():
    # Wrap the ADK Agent and instantiate handler (defaults to agent.name)
    adapter = ADKAgentAdapter(agent)
    handler = GoogleADKHandler(adapter)

    # Create FastAPI app with only this handler
    app = create_app(
        use_handler_discovery=False,
        custom_handlers=[handler],
        default_handler=handler
    )

    # Start server
    logger.info(f"Starting A2A Pirate Agent Server on http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
```

## Handler Details

- **`google_adk_handler`** now auto‑wraps raw ADK `Agent` instances via `ADKAgentAdapter` so `.invoke()`/`.stream()` always exist.
- **`prepare_handler_params`** treats the `name` parameter as a literal, allowing YAML overrides without import errors.

### Custom Handler Development

Subclass `TaskHandler`, implement `process_task`, and register via:

- **Automatic discovery** (`--handler-package`)
- **Entry points** in `setup.py` under `a2a.task_handlers`

### Installation

Clone the repo and install the core library:

```bash
git clone https://github.com/yourusername/a2a.git
cd a2a
pip install -e .
```

Install optional extras as needed:

```bash
pip install -e ".[jsonrpc]"    # core JSON-RPC only
pip install -e ".[server]"     # HTTP, WS, SSE server
pip install -e ".[client]"     # CLI client
pip install -e ".[adk]"        # Google ADK agent support
pip install -e ".[full]"       # All features
```

After installation, run the server or client using `uv run`:

```bash
uv run a2a-server --host 0.0.0.0 --port 8000 --log-level info
uv run a2a-client --help
```

### Requirements

- Python 3.9+
- HTTPX, WebSockets (for client)
- FastAPI, Uvicorn (for server)
- Pydantic v2+ (for JSON-RPC)

### Testing

```bash
pytest
```

