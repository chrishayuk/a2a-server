# A2A: Agent-to-Agent Communication Server

A lightweight, transport-agnostic framework for agent-to-agent communication based on JSON-RPC, implementing the [A2A Protocol](https://github.com/a2a-proto/a2a-protocol).

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
  
- **Intuitive URL Structure**:
  - Direct handler mounting at `/{handler_name}/rpc`, `/{handler_name}/ws`, and `/{handler_name}/events`
  - Default handler accessible at root paths (`/rpc`, `/ws`, `/events`)
  - Handler health checks at `/{handler_name}`

- **A2A Protocol Compliant**:
  - Agent Cards at `/.well-known/agent.json` and `/{handler_name}/.well-known/agent.json`
  - Standard Task/Message/Artifact structure
  - Streaming support

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

# List all registered routes (useful for debugging)
uv run a2a-server --list-routes

# Register additional handler packages
uv run a2a-server --handler-package my_custom_module.handlers

# Disable automatic handler discovery
uv run a2a-server --no-discovery
```

### Example: Configuring Agents via YAML

You can configure multiple agents with their capabilities and agent cards in YAML:

```yaml
server:
  port: 8000

handlers:
  use_discovery: false
  default: chef_agent

  pirate_agent:
    type: a2a.server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: a2a.server.sample_agents.pirate_agent.pirate_agent
    name: pirate_agent
    agent_card:
      name: Pirate Agent
      description: "Converts your text into salty pirate‑speak"
      url: "https://pirate.example.com"
      version: "0.1.0"
      documentationUrl: "https://pirate.example.com/docs"
      provider:
        organization: "Acme"
        url: "https://acme.example.com"
      capabilities:
        streaming: true
        pushNotifications: false
      authentication:
        schemes:
          - "Bearer"
      defaultInputModes:
        - "text/plain"
      defaultOutputModes:
        - "text/plain"
      skills:
        - id: pirate-talk
          name: Pirate Talk
          description: "Turn any message into pirate lingo"
          tags:
            - pirate
            - fun
          examples:
            - "Arrr! Give me yer loot!"

  chef_agent:
    type: a2a.server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: a2a.server.sample_agents.chef_agent.chef_agent
    name: chef_agent
    agent_card:
      name: Chef Agent
      description: "Suggests delicious recipes from your ingredients"
      # Other fields can be automatically derived...
```

Then launch:

```bash
uv run a2a-server --config agent.yaml --log-level debug
```

### Interacting with the Server

```bash
# Create a task with default handler
curl -N -X POST http://127.0.0.1:8000/rpc \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tasks/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{ "type":"text","text":"What can I make with chicken?" }]
      }
    }
  }'

# Create a task with specific handler
curl -N -X POST http://127.0.0.1:8000/pirate_agent/rpc \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tasks/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{ "type":"text","text":"Tell me about the sea" }]
      }
    }
  }'

# Stream events from default handler
curl -N http://127.0.0.1:8000/events

# Stream events from specific handler
curl -N http://127.0.0.1:8000/pirate_agent/events

# Get the default agent card (A2A Protocol compliant)
curl http://127.0.0.1:8000/.well-known/agent.json

# Get a specific handler's agent card
curl http://127.0.0.1:8000/pirate_agent/.well-known/agent.json

# Check handler health
curl http://127.0.0.1:8000/pirate_agent
```

## URL Structure

The server provides a consistent URL structure:

### Default Handler
- `/rpc` - JSON-RPC endpoint for the default handler
- `/ws` - WebSocket endpoint for the default handler  
- `/events` - SSE endpoint for the default handler
- `/.well-known/agent.json` - Agent Card for the default handler (A2A Protocol compliant)

### Specific Handlers
- `/{handler_name}/rpc` - JSON-RPC endpoint for a specific handler
- `/{handler_name}/ws` - WebSocket endpoint for a specific handler
- `/{handler_name}/events` - SSE endpoint for a specific handler
- `/{handler_name}/.well-known/agent.json` - Agent Card for a specific handler (A2A Protocol compliant)

### Health Checks
- `/` - Root health check with information about all handlers
- `/{handler_name}` - Handler-specific health check

## Agent Cards

The server implements the A2A Protocol's Agent Card specification. Agent cards contain information about the agent's:

- Name, description, and version
- Provider information
- Capabilities (streaming, push notifications)
- Authentication requirements
- Supported input/output modes
- Skills (capabilities the agent can perform)

Agent cards are generated from:
1. YAML configuration in the `agent_card` section
2. Dynamically detected capabilities (streaming support, etc.)
3. Reasonable defaults for missing fields

## Handler Details

- **`google_adk_handler`** wraps raw Google ADK `Agent` instances via `ADKAgentAdapter` so `.invoke()`/`.stream()` always exist.
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