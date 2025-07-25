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
  chuk_pirate:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler
    agent: a2a_server.sample_agents.chuk_pirate.create_pirate_agent
    name: chuk_pirate
    enable_sessions: true
    enable_tools: false
    provider: "openai"
    model: "gpt-4o-mini"
```

Set your OpenAI API key and start the server:

```bash
export OPENAI_API_KEY=your-key-here
uv run a2a-server --config agent.yaml
```

That's it! Your server is now running with a pirate-speaking agent at `http://localhost:8000`.

## 🔐 Environment Variables

### Required API Keys

```bash
# LLM Provider Keys
export OPENAI_API_KEY=your-openai-key
export ANTHROPIC_API_KEY=your-anthropic-key
export PERPLEXITY_API_KEY=your-perplexity-key
```

### Server Configuration

```bash
# Network Configuration
export HOST=0.0.0.0              # Server bind address
export PORT=8000                 # Server port

# Security (Production)
export A2A_ADMIN_TOKEN=your-secret-admin-token
export A2A_BEARER_TOKEN=your-api-bearer-token
```

### Session Management

```bash
# Session Storage
export SESSION_PROVIDER=redis    # or "memory" (default)
export SESSION_REDIS_URL=redis://localhost:6379
```

### MCP (Model Context Protocol) Servers

For agents with tool capabilities:

```bash
# Single MCP Server
export MCP_SERVER_URL=https://your-mcp-server.com

# Multiple MCP Servers
export MCP_SERVER_NAME_MAP='{"perplexity":"perplexity_server","time":"time_server"}'
export MCP_SERVER_URL_MAP='{"perplexity":"https://perplexity-mcp.com","time":"https://time-mcp.com"}'
export MCP_BEARER_TOKEN=your-mcp-auth-token
```

### Feature Toggles

```bash
# Disable specific features
export A2A_DISABLE_SESSION_ROUTES=1      # Hide session HTTP routes
export A2A_DISABLE_SESSION_EXPORT=1      # Hide import/export endpoints
export A2A_DISABLE_HEALTH_ROUTES=0       # Hide health endpoints

# Development/Debug
export DEBUG_A2A=1                       # Enable debug mode
export DEBUG_LEVEL=DEBUG                 # Set log level
```

### Monitoring & Metrics

```bash
# OpenTelemetry
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_SERVICE_NAME=a2a-server

# Prometheus
export PROMETHEUS_METRICS=true
export CONSOLE_METRICS=false
```

## 🤖 Built-in Agent Types

A2A Server supports multiple agent implementations:

### ChukAgent (Recommended)
Modern async agents with tool support and session management:

```yaml
handlers:
  my_agent:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler
    agent: a2a_server.sample_agents.chuk_pirate.create_pirate_agent
    enable_sessions: true
    enable_tools: true
    provider: "openai"
    model: "gpt-4o-mini"
```

### Google ADK Agents (Legacy)
Compatible with Google Agent Development Kit:

```yaml
handlers:
  legacy_agent:
    type: a2a_server.tasks.handlers.adk.google_adk_handler.GoogleADKHandler
    agent: a2a_server.sample_agents.pirate_agent.pirate_agent
    use_sessions: false
```

## 🛠️ MCP Agent Configuration

For agents with tool capabilities, you can configure MCP (Model Context Protocol) servers:

### 1. Create MCP Configuration File

Create a `mcp_config.json` file:

```json
{
  "mcpServers": {
    "time": {
      "command": "uvx",
      "args": [
        "mcp-server-time",
        "--local-timezone=America/New_York"
      ],
      "description": "Time and timezone utilities"
    },
    "filesystem": {
      "command": "uvx",
      "args": ["mcp-server-filesystem", "/allowed/path"],
      "description": "File system operations"
    },
    "web_search": {
      "command": "python",
      "args": ["-m", "mcp_server_web_search"],
      "env": {
        "SEARCH_API_KEY": "your-search-api-key"
      },
      "description": "Web search capabilities"
    }
  }
}
```

### 2. Configure Agent with MCP Tools

```yaml
handlers:
  time_agent:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler
    agent: a2a_server.sample_agents.time_agent.create_time_agent
    name: time_agent
    
    # Enable tools
    enable_tools: true
    debug_tools: true
    
    # MCP Configuration
    mcp_transport: "stdio"              # or "sse" for HTTP
    mcp_config_file: "mcp_config.json"
    mcp_servers: ["time", "filesystem"]
    tool_namespace: "tools"
    max_concurrency: 4
    tool_timeout: 30.0
```

### 3. Install MCP Servers

```bash
# Install popular MCP servers
uvx install mcp-server-time
uvx install mcp-server-filesystem
uvx install mcp-server-brave-search
uvx install mcp-server-everything

# Or install via pip
pip install mcp-server-time mcp-server-filesystem
```

### 4. SSE MCP Servers (Remote)

For remote MCP servers over HTTP:

```yaml
handlers:
  perplexity_agent:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler
    agent: a2a_server.sample_agents.perplexity_agent.create_perplexity_agent
    
    enable_tools: true
    mcp_transport: "sse"
    mcp_sse_servers:
      - name: "perplexity_server"
        url: "https://your-perplexity-mcp.com"
    tool_namespace: "sse"
```

With environment variables:

```bash
export MCP_SERVER_URL_MAP='{"perplexity_server":"https://your-mcp.com"}'
export MCP_BEARER_TOKEN="your-auth-token"
```

## 📋 Complete Agent.yaml Example

```yaml
server:
  host: 0.0.0.0
  port: 8000

# Logging configuration
logging:
  level: "info"
  quiet_modules:
    "uvicorn": "WARNING"
    "google.adk": "WARNING"
    "LiteLLM": "ERROR"

handlers:
  use_discovery: false
  default_handler: chuk_pirate

  # Modern ChukAgent with sessions
  chuk_pirate:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler
    agent: a2a_server.sample_agents.chuk_pirate.create_pirate_agent
    name: chuk_pirate
    
    # Session configuration
    session_sharing: true
    shared_sandbox_group: "global_user_sessions"
    enable_sessions: true
    infinite_context: true
    token_threshold: 4000
    session_ttl_hours: 24
    
    # Model configuration
    provider: "openai"
    model: "gpt-4o-mini"
    streaming: true
    
    # Tool configuration
    enable_tools: false
    debug_tools: false
    
    agent_card:
      name: Pirate Agent
      description: "Captain Blackbeard's Ghost with conversation memory"
      capabilities:
        streaming: true
        sessions: true
        tools: false

  # MCP-enabled agent with tools
  time_agent:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler
    agent: a2a_server.sample_agents.time_agent.create_time_agent
    name: time_agent
    
    enable_sessions: false
    enable_tools: true
    debug_tools: true
    
    # MCP configuration
    mcp_transport: "stdio"
    mcp_config_file: "time_mcp_config.json"
    mcp_servers: ["time"]
    tool_namespace: "tools"
    
    provider: "openai"
    model: "gpt-4o-mini"
    
    agent_card:
      name: Time Agent
      description: "Time and timezone assistant with MCP tools"
      capabilities:
        tools: true
        streaming: true

  # Research agent with remote MCP
  perplexity_agent:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler
    agent: a2a_server.sample_agents.perplexity_agent.create_perplexity_agent
    name: perplexity_agent
    
    enable_tools: true
    mcp_transport: "sse"
    tool_namespace: "sse"
    
    provider: "openai"
    model: "gpt-4o"
    
    agent_card:
      name: Perplexity Agent
      description: "Advanced research agent with search tools"
      capabilities:
        tools: true
        streaming: true
```

## 🔍 Code Quality Analysis

### ✅ Strengths
- **Async-first architecture** with proper resource management
- **Comprehensive session management** with external storage
- **Robust error handling** with circuit breakers and retries
- **Memory-managed caching** with automatic cleanup
- **Pluggable handler system** with automatic discovery
- **Multi-transport support** (HTTP, WebSocket, SSE)

### ⚠️ Areas for Improvement

## 1. Reduce Code Duplication

### Session Management Patterns
Multiple files repeat similar session setup logic:

```python
# Instead of repeating this pattern:
def _determine_session_sharing(self, session_sharing, shared_sandbox_group):
    if session_sharing is not None:
        return session_sharing
    if shared_sandbox_group is not None:
        return True
    return False

# Create a shared utility:
# a2a_server/utils/session_utils.py
class SessionConfigResolver:
    @staticmethod
    def determine_sharing(session_sharing, shared_sandbox_group):
        """Centralized logic for session sharing determination"""
        if session_sharing is not None:
            return session_sharing
        return shared_sandbox_group is not None
```

### Agent Factory Patterns
The agent creation logic is repeated across sample agents:

```python
# Create a base factory class:
# a2a_server/agents/base_factory.py
class BaseAgentFactory:
    def __init__(self, agent_class, default_config=None):
        self.agent_class = agent_class
        self.default_config = default_config or {}
        
    def create(self, **kwargs):
        config = {**self.default_config, **kwargs}
        return self.agent_class(**config)
        
    def create_cached(self, cache_key=None, **kwargs):
        # Implement caching logic here
        pass
```

## 2. Improve Error Handling

### Centralized Error Types
Create a unified error hierarchy:

```python
# a2a_server/exceptions.py
class A2AError(Exception):
    """Base exception for A2A server"""
    pass

class SessionError(A2AError):
    """Session-related errors"""
    pass

class HandlerError(A2AError):
    """Handler-related errors"""
    pass

class ToolError(A2AError):
    """Tool execution errors"""
    pass
```

### Error Context Management
```python
# a2a_server/utils/error_context.py
class ErrorContext:
    def __init__(self, operation: str, **context):
        self.operation = operation
        self.context = context
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            logger.error(f"Error in {self.operation}: {exc_val}", extra=self.context)
```

## 3. Configuration Management

### Centralized Config Validation
```python
# a2a_server/config/validator.py
from pydantic import BaseModel
from typing import Optional, Dict, Any

class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000

class AuthConfig(BaseModel):
    bearer_token: Optional[str] = None
    exclude_paths: list[str] = []

class A2AConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    auth: AuthConfig = AuthConfig()
    handlers: Dict[str, Any] = {}
    
    class Config:
        extra = "allow"  # Allow additional fields
```

## 4. Testing Infrastructure

### Create Test Utilities
```python
# tests/utils/fixtures.py
import pytest
from a2a_server.app import create_app
from a2a_server.tasks.task_manager import TaskManager

@pytest.fixture
def test_app():
    """Create test app with minimal config"""
    return create_app(
        handlers=[],
        use_discovery=False,
        docs_url=None
    )

@pytest.fixture
def mock_session_store():
    """Mock session store for testing"""
    # Implementation here
    pass

@pytest.fixture
def sample_task_handler():
    """Create a simple test handler"""
    # Implementation here
    pass
```

### Integration Test Framework
```python
# tests/integration/test_handlers.py
class HandlerTestCase:
    """Base class for handler integration tests"""
    
    def setup_method(self):
        self.app = create_test_app()
        self.client = TestClient(self.app)
        
    async def test_handler_lifecycle(self):
        """Test complete handler lifecycle"""
        # Create task
        response = await self.create_task("test message")
        task_id = response.json()["id"]
        
        # Monitor progress
        await self.wait_for_completion(task_id)
        
        # Verify results
        task = await self.get_task(task_id)
        assert task["status"]["state"] == "completed"
```

## 5. Performance Optimizations

### Connection Pooling
```python
# a2a_server/utils/connection_pool.py
class ConnectionPool:
    def __init__(self, max_size=10):
        self.max_size = max_size
        self.pool = asyncio.Queue(maxsize=max_size)
        
    async def acquire(self):
        """Get connection from pool"""
        pass
        
    async def release(self, connection):
        """Return connection to pool"""
        pass
```

### Caching Strategy
```python
# a2a_server/cache/manager.py
class CacheManager:
    def __init__(self, redis_url=None):
        self.redis_url = redis_url
        self.local_cache = {}
        
    async def get(self, key: str):
        """Get from cache with fallback to local"""
        pass
        
    async def set(self, key: str, value: Any, ttl: int = 300):
        """Set in cache with TTL"""
        pass
```

## 6. Monitoring & Observability

### Structured Logging
```python
# a2a_server/logging/structured.py
import structlog

def configure_structured_logging():
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
```

### Health Check Framework
```python
# a2a_server/health/checker.py
class HealthChecker:
    def __init__(self):
        self.checks = {}
        
    def register_check(self, name: str, check_func):
        """Register a health check function"""
        self.checks[name] = check_func
        
    async def run_checks(self):
        """Run all health checks"""
        results = {}
        for name, check_func in self.checks.items():
            try:
                results[name] = await check_func()
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}
        return results
```

## 7. Security Enhancements

### Rate Limiting
```python
# a2a_server/middleware/rate_limit.py
from starlette.middleware.base import BaseHTTPMiddleware
import time

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, calls: int = 100, period: int = 60):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.clients = {}
        
    async def dispatch(self, request, call_next):
        client_ip = request.client.host
        
        # Check rate limit
        if self.is_rate_limited(client_ip):
            return JSONResponse(
                {"error": "Rate limit exceeded"}, 
                status_code=429
            )
            
        return await call_next(request)
```

### Input Validation
```python
# a2a_server/validation/message.py
from pydantic import BaseModel, validator

class MessageValidator(BaseModel):
    content: str
    max_length: int = 10000
    
    @validator('content')
    def validate_content(cls, v):
        if len(v) > cls.max_length:
            raise ValueError(f'Content too long: {len(v)} > {cls.max_length}')
        return v
```

## 8. Documentation Improvements

### API Documentation
Add comprehensive OpenAPI documentation:

```python
# In handler classes, add proper docstrings:
async def process_task(self, task_id: str, message: Message, session_id: Optional[str] = None):
    """
    Process a task asynchronously.
    
    Args:
        task_id: Unique identifier for the task
        message: The message to process containing user input
        session_id: Optional session ID for conversation context
        
    Yields:
        TaskStatusUpdateEvent: Status updates as the task progresses
        TaskArtifactUpdateEvent: Artifacts generated during processing
        
    Raises:
        HandlerError: If the handler encounters an unrecoverable error
        TimeoutError: If the task exceeds the configured timeout
    """
```

### Configuration Examples
Create comprehensive configuration examples:

```yaml
# config/examples/production.yaml
server:
  host: "0.0.0.0"
  port: 8000

auth:
  bearer_token: "${A2A_BEARER_TOKEN}"
  exclude_paths:
    - "/health"
    - "/ready"
    - "/.well-known/agent.json"

handlers:
  use_discovery: true
  handler_packages:
    - "a2a_server.tasks.handlers"
  
  default_handler: "chuk_pirate"
  
  chuk_pirate:
    type: "a2a_server.tasks.handlers.chuk.chuk_agent_handler.ChukAgentHandler"
    agent: "a2a_server.sample_agents.chuk_pirate.create_pirate_agent"
    session_sharing: true
    shared_sandbox_group: "production_agents"
    # Agent configuration
    provider: "openai"
    model: "gpt-4o-mini"
    enable_sessions: true
    enable_tools: true
```

## Implementation Priority

1. **High Priority**
   - Configuration validation (Pydantic models)
   - Centralized error handling
   - Basic test infrastructure

2. **Medium Priority**
   - Reduce code duplication in session management
   - Structured logging
   - Rate limiting middleware

3. **Low Priority**
   - Advanced caching strategies
   - Connection pooling
   - Comprehensive monitoring

## Next Steps

1. Start with configuration validation using Pydantic
2. Create centralized error types and context management
3. Set up basic test infrastructure
4. Gradually refactor duplicated code into shared utilities
5. Add comprehensive documentation and examples

This refactoring will make the codebase more maintainable, testable, and easier to extend while preserving all existing functionality.