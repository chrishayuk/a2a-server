# A2A Server: Agent-to-Agent Communication Framework

A lightweight, transport-agnostic framework for agent-to-agent communication based on JSON-RPC, implementing the [A2A Protocol](https://github.com/a2a-proto/a2a-protocol).

## 🚀 Quick Start

### Install from PyPI

```bash
pip install a2a-server
```

### Run with a Sample Agent

Create a minimal `agent.yaml` configuration file:

```yaml
server:
  host: 0.0.0.0
  port: 8000

handlers:
  pirate_agent:
    type: a2a_server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: a2a_server.sample_agents.pirate_agent.pirate_agent
    name: pirate_agent
```

Start the server:

```bash
uv run a2a-server --config agent.yaml
```

That's it! Your server is now running with a pirate-speaking agent.

## 🔍 What's in the Framework

A2A Server provides:

- **Multiple Transport Layers**: HTTP, WebSocket, Server-Sent Events (SSE)
- **Flexible Handler System**: Easily create and register custom agent handlers
- **Google ADK Integration**: Seamless use of Google Agent Development Kit agents
- **Auto-Discovery**: Find handlers through packages or entry points
- **Agent Cards**: A2A Protocol compatible agent descriptions
- **Metrics & Observability**: OpenTelemetry and Prometheus support
- **Async-First Design**: Modern concurrency with asyncio.TaskGroup

## 🤖 Using the Built-in Agents

A2A Server comes with sample agents that you can use right away:

- **Pirate Agent**: Converts text into pirate-speak
- **Chef Agent**: Provides cooking advice and recipes
- **Echo Agent**: Simple agent that echoes messages (useful for testing)

### Configure Multiple Agents

Update your `agent.yaml` to include multiple agents:

```yaml
server:
  host: 0.0.0.0
  port: 8000

handlers:
  use_discovery: false
  default: pirate_agent  # This will be the default handler

  pirate_agent:
    type: a2a_server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: a2a_server.sample_agents.pirate_agent.pirate_agent
    name: pirate_agent

  chef_agent:
    type: a2a_server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: a2a_server.sample_agents.chef_agent.chef_agent
    name: chef_agent
```

## 🛠️ Creating Your Own Agent

### 1. Create a Google ADK Agent

```python
# my_agents/trivia_agent.py
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

trivia_agent = Agent(
    name="trivia_agent",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Provides fun trivia facts",
    instruction="You are a trivia expert. When users ask you questions, provide interesting and accurate trivia facts related to their query. Keep your responses brief, entertaining, and educational."
)
```

### 2. Register in Your Config

```yaml
# agent.yaml
handlers:
  trivia_agent:
    type: a2a_server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: my_agents.trivia_agent.trivia_agent
    name: trivia_agent
```

### 3. Start the Server with Your Module in Python Path

```bash
PYTHONPATH=/path/to/my_agents_directory a2a-server --config agent.yaml
```

## 🧪 Creating a Custom Handler

For more advanced use cases, create a custom handler:

```python
# my_handlers/custom_handler.py
import asyncio
from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

class CustomHandler(TaskHandler):
    @property
    def name(self) -> str:
        return "custom"
    
    async def process_task(self, task_id, message, session_id=None):
        # First yield a "working" status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        # Extract text from message
        text = ""
        if message.parts:
            part_data = message.parts[0].model_dump(exclude_none=True)
            if "text" in part_data:
                text = part_data["text"] or ""
        
        # Process the message (your custom logic here)
        response_text = f"Custom response to: {text}"
        
        # Create and yield an artifact
        response_part = TextPart(type="text", text=response_text)
        artifact = Artifact(name="custom_response", parts=[response_part], index=0)
        yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
        
        # Finally, yield completion status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True
        )
```

Register it in your `agent.yaml`:

```yaml
handlers:
  custom:
    type: my_handlers.custom_handler.CustomHandler
    name: custom
```

## 🧪 Testing Your Agents

### Using a2a-cli

The easiest way to test your agents is with a2a-cli:

```bash
# Install the CLI
pip install a2a-cli

# Connect to your server's default agent
a2a-cli --server http://localhost:8000

# Connect to a specific agent
a2a-cli --server http://localhost:8000/pirate_agent
```

### Using curl

#### Create a Task

```bash
curl -X POST http://localhost:8000/rpc \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tasks/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{"type":"text","text":"Tell me about pirates"}]
      }
    }
  }'
```

#### Stream Events for a Task

```bash
curl -N http://localhost:8000/events?task_ids=<task_id>
```

#### Use a Specific Agent

```bash
curl -X POST http://localhost:8000/chef_agent/rpc \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tasks/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{"type":"text","text":"What can I make with chicken and rice?"}]
      }
    }
  }'
```

#### Get Agent Metadata

```bash
curl http://localhost:8000/.well-known/agent.json
curl http://localhost:8000/pirate_agent/.well-known/agent.json
```

### Using WebSockets

For WebSocket testing, use the `websocat` tool:

```bash
# Install websocat
cargo install websocat

# Connect to default agent
websocat ws://localhost:8000/ws

# Connect to specific agent
websocat ws://localhost:8000/pirate_agent/ws
```

Then send a JSON-RPC request:

```json
{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"message":{"role":"user","parts":[{"type":"text","text":"Hello there!"}]}}}
```

## 🚀 Advanced Configuration

### Enable Metrics

```bash
# Enable Prometheus metrics
export PROMETHEUS_METRICS=true
a2a-server --config agent.yaml

# Use OpenTelemetry
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
a2a-server --config agent.yaml
```

### Log Levels

```bash
# Set log level
a2a-server --config agent.yaml --log-level debug
```

### Handler Discovery

```bash
# Add custom handler packages
a2a-server --config agent.yaml --handler-package my_custom_handlers
```

## 📚 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/rpc` | JSON-RPC endpoint for the default handler |
| `/{handler}/rpc` | JSON-RPC endpoint for a specific handler |
| `/ws` | WebSocket endpoint for the default handler |
| `/{handler}/ws` | WebSocket endpoint for a specific handler |
| `/events` | SSE endpoint for the default handler |
| `/{handler}/events` | SSE endpoint for a specific handler |
| `/.well-known/agent.json` | Agent Card for the default handler |
| `/{handler}/.well-known/agent.json` | Agent Card for a specific handler |
| `/metrics` | Prometheus metrics (when enabled) |

## 🔒 Security Note

For production deployment, we recommend placing the A2A server behind an authentication layer, as the SSE and WebSocket endpoints do not include authentication by default.

## 🌟 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.