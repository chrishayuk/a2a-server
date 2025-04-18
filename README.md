# A2A: Agent-to-Agent Communication Server

A lightweight, transport-agnostic server for agent-to-agent communication based on JSON-RPC.

## Server

The A2A server provides a flexible JSON-RPC interface for agent-to-agent communication with support for multiple transport protocols.

### Features

- **Multiple Transport Protocols**:
  - HTTP JSON-RPC endpoint
  - WebSocket for bidirectional communication
  - Server-Sent Events (SSE) for real-time updates
  - Standard I/O mode for CLI applications

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
  - Plugin system via entry points
  - Custom handler development

### Running the Server

```bash
# Basic usage (HTTP, WebSocket, and SSE on port 8000)
a2a-server

# Specify host and port
a2a-server --host 0.0.0.0 --port 8000

# Enable detailed logging
a2a-server --log-level debug

# Run in standard I/O mode (for CLI applications)
a2a-server --stdio

# List all available task handlers
a2a-server --list-handlers

# Specify additional handler packages
a2a-server --handler-package my_custom_module.handlers

# Disable automatic handler discovery
a2a-server --no-discovery
```

### Server Endpoints

- `POST /rpc` - HTTP JSON-RPC endpoint
- `GET /ws` - WebSocket endpoint for bidirectional JSON-RPC
- `GET /events` - Server-Sent Events (SSE) for real-time updates

### JSON-RPC Methods

| Method | Description | Parameters |
|--------|-------------|------------|
| `tasks/send` | Create a new task | `message`, `session_id` (optional) |
| `tasks/get` | Get task details | `id` |
| `tasks/cancel` | Cancel a running task | `id` |
| `tasks/sendSubscribe` | Create a task and subscribe to updates | `message`, `session_id` (optional), `handler` (optional) |
| `tasks/resubscribe` | Reconnect to event stream | `id` |

### Task Lifecycle

Tasks follow a state machine with these transitions:

- `submitted` → `working` → `completed` / `failed` / `canceled`
- `working` → `input_required` → `working` (for interactive tasks)

### Task Handlers

Tasks are processed by handlers that implement specific functionality. The server includes a basic `EchoHandler` by default and can discover additional handlers automatically.

#### Built-in Handlers

- `echo` - Simple echo handler that returns the input message

#### Creating Custom Handlers

Create a custom handler by subclassing `TaskHandler`:

```python
from a2a.server.tasks.task_handler import TaskHandler
from a2a.json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent, Role
)

class MyCustomHandler(TaskHandler):
    @property
    def name(self) -> str:
        return "my_handler"
    
    async def process_task(self, task_id, message, session_id=None):
        # Update status to working
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        # Process the message...
        
        # Yield completion
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True
        )
```

#### Handler Discovery

Handlers are automatically discovered from:

1. Built-in handlers in `a2a.server.tasks.handlers`
2. Custom packages specified with `--handler-package`
3. Entry points in installed packages

To register handlers via entry points, add this to your `setup.py`:

```python
setup(
    name="my-a2a-handlers",
    # ...
    entry_points={
        "a2a.task_handlers": [
            "my_handler = my_module.handlers:MyCustomHandler",
        ],
    },
)
```

### Implementation Details

The server is built on these core components:

- **TaskManager**: Handles task creation, state transitions, and artifact management
- **EventBus**: Provides publish/subscribe functionality for real-time updates
- **JSONRPCProtocol**: Implements the JSON-RPC 2.0 specification
- **TaskHandlerRegistry**: Manages task handler registration and selection

The architecture is fully asynchronous, using Python's asyncio and FastAPI for high performance.

### Example: Server Log Output

A successful task execution produces log output like this:

```
2025-04-18 19:29:38,563 INFO a2a.server.methods: Task created feb82384-544d-4ba1-8b81-0f41e97c128a, scheduling background runner
2025-04-18 19:29:39,564 DEBUG a2a.server.methods: Updating task feb82384-544d-4ba1-8b81-0f41e97c128a to working
2025-04-18 19:29:39,564 DEBUG a2a.server.methods: Task feb82384-544d-4ba1-8b81-0f41e97c128a initial text: 'tell me a joke'
2025-04-18 19:29:39,564 DEBUG a2a.server.methods: Adding artifact to task feb82384-544d-4ba1-8b81-0f41e97c128a: Echo: tell me a joke
2025-04-18 19:29:39,565 DEBUG a2a.server.methods: Updating task feb82384-544d-4ba1-8b81-0f41e97c128a to completed
2025-04-18 19:29:39,565 INFO a2a.server.methods: Background runner completed for task feb82384-544d-4ba1-8b81-0f41e97c128a
```

## Installation

```bash
# Install from source
git clone https://github.com/yourusername/a2a.git
cd a2a
pip install -e .

# Install with custom handlers development mode
pip install -e ".[dev]"
```

## Requirements

- Python 3.9+
- FastAPI
- Uvicorn
- Pydantic v2+
- WebSockets

## Development

### Adding a new Handler

1. Create a new module in `a2a/server/tasks/handlers/`
2. Subclass `TaskHandler` and implement required methods
3. The handler will be automatically discovered

Or create a separate package with entry points as described above.

### Running Tests

```bash
pytest
```