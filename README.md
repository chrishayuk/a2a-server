# Getting Started with A2A: Agent-to-Agent Framework

A lightweight, transport-agnostic framework for agent-to-agent communication based on JSON-RPC, implementing the [A2A Protocol](https://github.com/a2a-proto/a2a-protocol).

## 🚀 Creating a New A2A Project

### 1. Project Structure Setup

```bash
# Create project directory
mkdir my-a2a-project
cd my-a2a-project

# Initialize Python project structure
mkdir -p src/my_a2a_project/handlers
mkdir -p src/my_a2a_project/sample_agents
touch src/my_a2a_project/__init__.py
touch src/my_a2a_project/handlers/__init__.py
touch src/my_a2a_project/sample_agents/__init__.py
```

### 2. Create a pyproject.toml File

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-a2a-project"
version = "0.1.0"
description = "Your A2A project description"
readme = "README.md"
requires-python = ">=3.9"
dependencies = [
    "a2a-server>=0.1.0"
]

[tool.setuptools.packages.find]
where = ["src"]
include = ["my_a2a_project*"]

[project.scripts]
my-a2a-project = "my_a2a_project.main:app"
```

### 3. Create a Main Entry Point

Create a file at `src/my_a2a_project/main.py`:

```python
#!/usr/bin/env python3
"""
CLI entrypoint for my-a2a-project: delegates to run.py's run_server.
"""
# a2a imports
from a2a_server.run import run_server

# main entrypoint
def main():
    # call run server
    run_server()

# main entrypoint for script entry
def app():
    # call run server
    run_server()

# check for main entrypoint
if __name__ == "__main__":
    # call main
    main()
```

### 4. Create Your First Agent

Create a file at `src/my_a2a_project/sample_agents/greeting_agent.py`:

```python
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

# set the agent model
AGENT_MODEL = "openai/gpt-4o-mini"

# greeting agent
greeting_agent = Agent(
    name="greeting_agent",
    model=LiteLlm(model=AGENT_MODEL),
    description="A friendly greeting agent",
    instruction="You are a friendly assistant called Greeter. You will always greet users warmly and ask how they are doing today. Keep responses brief and friendly."
)
```

### 5. Create a Custom Handler (Optional)

Create a file at `src/my_a2a_project/handlers/custom_handler.py`:

```python
import asyncio

# a2a imports
from a2a_server.tasks.task_handler import TaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

class CustomHandler(TaskHandler):
    @property
    def name(self) -> str:
        return "custom"  # This must match the handler name in your YAML config
    
    async def process_task(self, task_id, message, session_id=None):
        # First yield a "working" status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        await asyncio.sleep(1)  # simulate work
        
        # Extract text from first part
        text = ""
        if message.parts:
            first_part = message.parts[0]
            part_data = first_part.model_dump(exclude_none=True)
            if "text" in part_data:
                text = part_data["text"] or ""
        
        # Create a custom response
        response_text = f"Custom handler received: {text}"
        response_part = TextPart(type="text", text=response_text)
        artifact = Artifact(name="custom_response", parts=[response_part], index=0)
        
        yield TaskArtifactUpdateEvent(
            id=task_id,
            artifact=artifact
        )
        
        # Finally, yield completion status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True
        )
```

Make sure to update your handlers `__init__.py` file:

```python
# src/my_a2a_project/handlers/__init__.py
"""
This package contains custom handlers for the A2A server.
"""

# Explicitly export the CustomHandler class for discovery
from my_a2a_project.handlers.custom_handler import CustomHandler

__all__ = ['CustomHandler']
```

### 6. Create Your Configuration File

Create a file named `agent.yaml` in your project root:

```yaml
server:
  host: 0.0.0.0
  port: 8000

handlers:
  use_discovery: true
  handler_packages: 
    - a2a_server.tasks.handlers
    - my_a2a_project.handlers
  default: greeting_agent

  greeting_agent:
    type: a2a_server.tasks.handlers.google_adk_handler.GoogleADKHandler
    agent: my_a2a_project.sample_agents.greeting_agent.greeting_agent
    name: greeting_agent
    agent_card:
      name: Greeting Agent
      description: "A friendly agent that greets you"
      version: "0.1.0"
      capabilities:
        streaming: true
      defaultInputModes:
        - "text/plain"
      defaultOutputModes:
        - "text/plain"
      skills:
        - id: greeting
          name: Greeting
          description: "Greets users warmly"
          tags:
            - greeting
            - friendly
          examples:
            - "Hello there!"
            
  custom:
    type: CustomHandler  # Just the class name since we added it to handler_packages
    name: custom
```

### 7. Install and Run Your Project

```bash
# Install your project in development mode
pip install -e .

# Run your A2A server with your configuration
uv run my-a2a-project --config agent.yaml

# Additional run options:
# Specify host and port
uv run my-a2a-project --host 0.0.0.0 --port 8000

# Enable detailed logging
uv run my-a2a-project --log-level debug

# Run in stdio JSON-RPC mode
uv run my-a2a-project --stdio

# List all available task handlers
uv run my-a2a-project --list-handlers

# List all registered routes (useful for debugging)
uv run my-a2a-project --list-routes

# Register additional handler packages
uv run my-a2a-project --handler-package another_module.handlers

# Disable automatic handler discovery
uv run my-a2a-project --no-discovery
```

### 8. Testing Your Agents

After starting your server, you can connect to it using the A2A client:

```bash
# Connect to your greeting agent
uv run a2a-cli --server greeting_agent

# Or connect to your custom handler
uv run a2a-cli --server custom
```

## Troubleshooting Common Issues

### Handler Not Found

If you see an error like `Handler class not found: CustomHandler`, check:

1. The handler class is properly named and exported in `__init__.py`
2. Your handler package is included in `handler_packages` in the YAML config
3. The `type` in your YAML uses the correct path or class name
4. The `name` property in your handler class matches the one in your configuration

### Agent Not Loading

If your agent isn't loading properly:

1. Verify the import path in your YAML configuration
2. Ensure your agent is properly instantiated
3. Check that the model is accessible 

### Server Double Initialization

The A2A server sometimes initializes twice. If this happens:

1. First it loads a default handler
2. Then it loads your configuration 

If handlers aren't registering correctly, check your logs to see which ones are being recognized.

## Extending Your Project

### Adding More Agents

To add more agents, create them in your `sample_agents` directory and update your YAML configuration.

### Creating Specialized Handlers

You can create specialized handlers by subclassing `TaskHandler` and implementing the `process_task` method to handle different types of requests.

### Customizing Agent Cards

Enhance your agent cards with more detailed information to better describe your agents' capabilities to users and other agents.

## Interacting with Your A2A Server

Once your server is running, you can interact with it using various methods:

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
        "parts":[{ "type":"text","text":"Hello, how are you?" }]
      }
    }
  }'

# Create a task with specific handler
curl -N -X POST http://127.0.0.1:8000/custom/rpc \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tasks/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{ "type":"text","text":"Process this message" }]
      }
    }
  }'

# Stream events from default handler
curl -N http://127.0.0.1:8000/events

# Stream events from specific handler
curl -N http://127.0.0.1:8000/custom/events

# Get the default agent card (A2A Protocol compliant)
curl http://127.0.0.1:8000/.well-known/agent.json

# Get a specific handler's agent card
curl http://127.0.0.1:8000/custom/.well-known/agent.json

# Check handler health
curl http://127.0.0.1:8000/custom
```

## Deployment

For production deployment:

```bash
# Build your package
python -m build

# Install in production environment
pip install my-a2a-project-0.1.0-py3-none-any.whl

# Run with gunicorn for production
gunicorn -k uvicorn.workers.UvicornWorker -w 4 my_a2a_project.main:app
```

## URL Structure

Your A2A server provides a consistent URL structure:

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

## Additional Resources

- [A2A Protocol Specification](https://github.com/a2a-proto/a2a-protocol)
- [Google ADK Documentation](https://developers.google.com/agent-development-kit)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)