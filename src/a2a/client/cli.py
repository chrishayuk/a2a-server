#!/usr/bin/env python3
# a2a/client/cli.py
"""
A2A Client CLI

Provides a rich, interactive command-line interface for the Agent-to-Agent protocol.
Includes commands to send, get, cancel, and watch tasks via various A2A transports.
"""
import argparse
import sys
import uuid
import asyncio
import logging
import json
import os
import signal
import atexit
from typing import Optional, List, Dict, Any

# Third-party imports
import typer
from rich import print
from rich.console import Console
from rich.panel import Panel

# A2A client imports
from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.spec import (
    TextPart,
    Message,
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.client.transport.stdio import JSONRPCStdioTransport

# Local imports
from a2a.client.chat.chat_handler import handle_chat_mode
from a2a.client.ui.ui_helpers import display_task_info, restore_terminal, clear_screen

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
def setup_logging(args):
    log_level = logging.DEBUG if args.debug else getattr(logging, args.log_level.upper())
    root_logger = logging.getLogger()
    cli_logger = logging.getLogger("a2a-client")
    http_logger = logging.getLogger("httpx") if 'httpx' in sys.modules else None
    sse_logger = logging.getLogger("a2a-client.sse")

    fmt = "%(asctime)s - %(levelname)s - %(message)s" if args.debug else "%(message)s"
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt))

    # Base levels
    root_logger.setLevel(logging.WARNING)
    cli_logger.setLevel(log_level)
    if http_logger:
        http_logger.setLevel(logging.WARNING if args.quiet else log_level)
    sse_logger.setLevel(logging.WARNING if args.quiet else log_level)

    # Clean handlers
    for lg in [root_logger, cli_logger, sse_logger]:
        lg.handlers.clear()
        lg.addHandler(console)
    if http_logger:
        http_logger.handlers.clear()
        http_logger.addHandler(console)

    return cli_logger

# -----------------------------------------------------------------------------
# Defaults for constructing endpoints
# -----------------------------------------------------------------------------
DEFAULT_HOST = "http://localhost:8000"
RPC_SUFFIX = "/rpc"
EVENTS_SUFFIX = "/events"

# -----------------------------------------------------------------------------
# Helper to resolve base URL from prefix or shorthand
# -----------------------------------------------------------------------------
def resolve_base(prefix: Optional[str]) -> str:
    if prefix:
        if prefix.startswith(("http://", "https://")):
            return prefix.rstrip("/")
        return f"{DEFAULT_HOST.rstrip('/')}/{prefix.strip('/')}"
    return DEFAULT_HOST

# -----------------------------------------------------------------------------
# Connection validation
# -----------------------------------------------------------------------------
async def check_server_running(base_url: str, quiet: bool = False) -> bool:
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            try:
                await client.get(base_url, timeout=3.0)
            except httpx.ConnectError:
                if not quiet:
                    logging.getLogger("a2a-client").error(
                        "Cannot connect to A2A server at %s", base_url
                    )
                return False
            except Exception as exc:
                if not quiet:
                    logging.getLogger("a2a-client").warning(
                        "Server check warning: %s", exc
                    )
                return False
    except ImportError:
        logging.getLogger("a2a-client").warning(
            "httpx not installed, skipping connection check"
        )
    return True

# -----------------------------------------------------------------------------
# Signal handling and cleanup
# -----------------------------------------------------------------------------
def restore_and_exit(signum=None, frame=None):
    """Clean up and exit on signal."""
    restore_terminal()
    sys.exit(0)

# Register cleanup on normal exit
atexit.register(restore_terminal)

# Register signal handlers
signal.signal(signal.SIGINT, restore_and_exit)
signal.signal(signal.SIGTERM, restore_and_exit)
if hasattr(signal, "SIGQUIT"):
    signal.signal(signal.SIGQUIT, restore_and_exit)

# -----------------------------------------------------------------------------
# Typer CLI app
# -----------------------------------------------------------------------------
app = typer.Typer(help="A2A Client CLI - Interactive client for the Agent-to-Agent protocol")

@app.callback(invoke_without_command=True)
def common_options(
    ctx: typer.Context,
    config_file: str = typer.Option(
        "~/.a2a/config.json",
        help="Path to configuration file with server definitions",
    ),
    server: str = typer.Option(
        None,
        help="Server URL or name from config (e.g. http://localhost:8000/chef_agent or pirate_agent)",
    ),
    debug: bool = typer.Option(
        False,
        help="Enable debug logging",
    ),
    quiet: bool = typer.Option(
        False,
        help="Suppress non-essential output",
    ),
    log_level: str = typer.Option(
        "INFO",
        help="Set the logging level. Options: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    ),
):
    """
    A2A Client - Interactive CLI for the Agent-to-Agent protocol.

    If no subcommand is provided, launches the interactive chat mode.
    """
    # Set up logging
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        typer.echo(f"Invalid log level: {log_level}")
        raise typer.Exit(1)
    
    # Create args object for logging setup
    class Args:
        pass
    
    args = Args()
    args.debug = debug
    args.quiet = quiet
    args.log_level = log_level
    
    setup_logging(args)
    
    # Expand config file path
    expanded_config = os.path.expanduser(config_file)
    
    # Get base URL from server parameter
    base_url = None
    if server:
        if server.startswith(("http://", "https://")):
            base_url = server
        else:
            # Might be a server name from config, or a path shorthand
            try:
                if os.path.exists(expanded_config):
                    with open(expanded_config, 'r') as f:
                        config = json.load(f)
                    
                    servers = config.get("servers", {})
                    if server in servers:
                        base_url = servers[server]
                    else:
                        # Use as path component
                        base_url = resolve_base(server)
                else:
                    # No config file, treat as path component
                    base_url = resolve_base(server)
            except Exception as e:
                logging.getLogger("a2a-client").warning(f"Error processing server name: {e}")
                base_url = resolve_base(server)
    
    # Store in context object
    ctx.obj = {
        "config_file": expanded_config,
        "base_url": base_url,
        "debug": debug,
        "quiet": quiet,
    }
    
    # If no subcommand specified, launch interactive mode
    if ctx.invoked_subcommand is None:
        try:
            asyncio.run(handle_chat_mode(base_url, expanded_config))
        except KeyboardInterrupt:
            logging.getLogger("a2a-client").info("Chat interrupted")
        except Exception as e:
            logging.getLogger("a2a-client").error(f"Error in chat mode: {e}")
        finally:
            restore_terminal()
        raise typer.Exit()

# -----------------------------------------------------------------------------
# Sub-commands for non-interactive use
# -----------------------------------------------------------------------------
@app.command()
def send(
    text: str = typer.Argument(..., help="Text of the task to send"),
    prefix: str = typer.Option(None, help="Handler mount or URL (e.g. pirate_agent or http://host:8000/chef_agent)"),
    wait: bool = typer.Option(False, help="Wait and stream status/artifacts"),
    color: bool = typer.Option(True, help="Colorize output"),
):
    """
    Send a text task to the A2A server and optionally wait for results.
    """
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX

    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    client = A2AClient.over_http(rpc_url)
    part = TextPart(type="text", text=text)
    message = Message(role="user", parts=[part])
    task_id = str(uuid.uuid4())
    params = TaskSendParams(id=task_id, sessionId=None, message=message)

    try:
        task = asyncio.run(client.send_task(params))
        
        # Use rich formatting for the output
        console = Console()
        
        if not wait:
            display_task_info(task, color)
        
        logging.getLogger("a2a-client").debug(
            "Send response: %s", json.dumps(task.model_dump(by_alias=True), indent=2)
        )
    except JSONRPCError as exc:
        logging.getLogger("a2a-client").error("Send failed: %s", exc)
        raise typer.Exit(1)
    except Exception as exc:
        logging.getLogger("a2a-client").error("Cannot connect to RPC at %s: %s", rpc_url, exc)
        raise typer.Exit(1)

    # Wait & stream
    if wait:
        sse_client = A2AClient.over_sse(rpc_url, events_url)

        async def _stream():
            try:
                from rich.live import Live
                from rich.text import Text
                from a2a.client.ui.ui_helpers import format_status_event, format_artifact_event
                
                console = Console()
                
                with Live("", refresh_per_second=4, console=console) as live:
                    async for evt in sse_client.send_subscribe(params):
                        if isinstance(evt, TaskStatusUpdateEvent):
                            live.update(Text.from_markup(format_status_event(evt)))
                            
                            if evt.final:
                                print(f"[green]Task {task_id} completed.[/green]")
                                break
                        elif isinstance(evt, TaskArtifactUpdateEvent):
                            live.update(Text.from_markup(format_artifact_event(evt)))
                        else:
                            live.update(Text(f"Unknown event: {type(evt).__name__}"))
            except Exception as e:
                logging.getLogger("a2a-client").exception("Stream error: %s", e)
            finally:
                if hasattr(sse_client.transport, "close"):
                    await sse_client.transport.close()

        try:
            asyncio.run(_stream())
        except KeyboardInterrupt:
            logging.getLogger("a2a-client").info("Stream interrupted")

@app.command()
def get(
    id: str = typer.Argument(..., help="Task ID to fetch"),
    prefix: str = typer.Option(None, help="Handler mount or URL"),
    json_output: bool = typer.Option(False, "--json", help="Output full JSON"),
    color: bool = typer.Option(True, help="Colorize output"),
):
    """
    Fetch a task by ID.
    """
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX

    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    client = A2AClient.over_http(rpc_url)
    # Create a proper TaskQueryParams object instead of a raw dict
    params = TaskQueryParams(id=id)

    try:
        task = asyncio.run(client.get_task(params))
        if json_output:
            # Use rich for pretty JSON
            from rich.json import JSON
            console = Console()
            console.print(JSON(task.model_dump_json(indent=2, by_alias=True)))
        else:
            display_task_info(task, color)
    except JSONRPCError as exc:
        logging.getLogger("a2a-client").error("Get failed: %s", exc)
        raise typer.Exit(1)
    except Exception as exc:
        logging.getLogger("a2a-client").error("Cannot connect to RPC at %s: %s", rpc_url, exc)
        raise typer.Exit(1)

@app.command()
def cancel(
    id: str = typer.Argument(..., help="Task ID to cancel"),
    prefix: str = typer.Option(None, help="Handler mount or URL"),
):
    """
    Cancel a task by ID.
    """
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX

    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    client = A2AClient.over_http(rpc_url)
    # Create a proper TaskIdParams object instead of a raw dict
    params = TaskIdParams(id=id)

    try:
        asyncio.run(client.cancel_task(params))
        console = Console()
        console.print(f"[green]Canceled task {id}[/green]")
    except Exception as exc:
        logging.getLogger("a2a-client").error("Cancel failed: %s", exc)
        raise typer.Exit(1)

@app.command()
def watch(
    id: str = typer.Argument(None, help="Existing task ID to watch"),
    text: str = typer.Option(None, help="Text to send and watch new task"),
    prefix: str = typer.Option(None, help="Handler mount or URL"),
):
    """
    Watch task events via SSE.
    
    Either watch an existing task or send a new task and watch it.
    """
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX

    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    client = A2AClient.over_sse(rpc_url, events_url)

    async def _watch():
        if id:
            # Watch existing task - using a proper TaskQueryParams object
            iterator = client.resubscribe(TaskQueryParams(id=id))
            print(f"Watching task {id}. Press Ctrl+C to stop...")
        elif text:
            # Send new task and watch it
            part = TextPart(type="text", text=text)
            message = Message(role="user", parts=[part])
            task_id = str(uuid.uuid4())
            params = TaskSendParams(id=task_id, sessionId=None, message=message)
            print(f"Sending task {task_id} and watching updates. Press Ctrl+C to stop...")
            iterator = client.send_subscribe(params)
        else:
            print("[red]Error: Either --id or --text must be specified.[/red]")
            return

        try:
            from rich.live import Live
            from rich.text import Text
            from a2a.client.ui.ui_helpers import format_status_event, format_artifact_event
            
            console = Console()
            
            with Live("", refresh_per_second=4, console=console) as live:
                async for evt in iterator:
                    if isinstance(evt, TaskStatusUpdateEvent):
                        live.update(Text.from_markup(format_status_event(evt)))
                        
                        if evt.final:
                            print(f"[green]Task completed.[/green]")
                            break
                    elif isinstance(evt, TaskArtifactUpdateEvent):
                        live.update(Text.from_markup(format_artifact_event(evt)))
                    else:
                        live.update(Text(f"Unknown event: {type(evt).__name__}"))
        except Exception as e:
            logging.getLogger("a2a-client").exception("Watch error: %s", e)
        finally:
            if hasattr(client.transport, "close"):
                await client.transport.close()

    try:
        asyncio.run(_watch())
    except KeyboardInterrupt:
        logging.getLogger("a2a-client").info("Watch interrupted")

@app.command()
def chat(
    config_file: str = typer.Option(
        "~/.a2a/config.json",
        help="Path to configuration file",
    ),
    server: str = typer.Option(
        None,
        help="Server URL or name",
    ),
):
    """
    Start interactive chat mode.
    """
    # Expand config file path
    expanded_config = os.path.expanduser(config_file)
    
    # Get base URL from server parameter
    base_url = None
    if server:
        if server.startswith(("http://", "https://")):
            base_url = server
        else:
            # Might be a server name from config, or a path shorthand
            try:
                if os.path.exists(expanded_config):
                    with open(expanded_config, 'r') as f:
                        config = json.load(f)
                    
                    servers = config.get("servers", {})
                    if server in servers:
                        base_url = servers[server]
                    else:
                        # Use as path component
                        base_url = resolve_base(server)
                else:
                    # No config file, treat as path component
                    base_url = resolve_base(server)
            except Exception as e:
                logging.getLogger("a2a-client").warning(f"Error processing server name: {e}")
                base_url = resolve_base(server)
    
    try:
        asyncio.run(handle_chat_mode(base_url, expanded_config))
    except KeyboardInterrupt:
        logging.getLogger("a2a-client").info("Chat interrupted")
    except Exception as e:
        logging.getLogger("a2a-client").error(f"Error in chat mode: {e}")
    finally:
        restore_terminal()

@app.command()
def stdio():
    """
    Run in stdio mode, acting as a JSON-RPC transport over stdin/stdout.
    
    This allows the client to be used as a subprocess-based agent.
    """
    # Create a client with stdio transport
    client = A2AClient.over_stdio()
    
    async def _run_stdio():
        try:
            logging.getLogger("a2a-client").info("Starting stdio mode, waiting for JSON-RPC input...")
            
            # Process incoming messages
            async for message in client.transport.stream():
                # Only process valid JSON-RPC requests
                if not isinstance(message, dict) or "method" not in message:
                    continue
                
                method = message.get("method")
                params = message.get("params", {})
                req_id = message.get("id")
                
                try:
                    # Route to appropriate method
                    if method == "tasks/send":
                        from a2a.json_rpc.spec import TaskSendParams
                        task_params = TaskSendParams.model_validate(params)
                        result = await client.send_task(task_params)
                        response = {
                            "jsonrpc": "2.0",
                            "result": result.model_dump(by_alias=True),
                            "id": req_id
                        }
                        print(json.dumps(response), flush=True)
                    
                    elif method == "tasks/get":
                        from a2a.json_rpc.spec import TaskQueryParams
                        task_params = TaskQueryParams.model_validate(params)
                        result = await client.get_task(task_params)
                        response = {
                            "jsonrpc": "2.0",
                            "result": result.model_dump(by_alias=True),
                            "id": req_id
                        }
                        print(json.dumps(response), flush=True)
                    
                    elif method == "tasks/cancel":
                        from a2a.json_rpc.spec import TaskIdParams
                        task_params = TaskIdParams.model_validate(params)
                        await client.cancel_task(task_params)
                        response = {
                            "jsonrpc": "2.0",
                            "result": None,
                            "id": req_id
                        }
                        print(json.dumps(response), flush=True)
                    
                    elif req_id is not None:
                        # Unknown method with ID - return error
                        response = {
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}"
                            },
                            "id": req_id
                        }
                        print(json.dumps(response), flush=True)
                
                except Exception as e:
                    if req_id is not None:
                        error_response = {
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32000,
                                "message": str(e)
                            },
                            "id": req_id
                        }
                        print(json.dumps(error_response), flush=True)
        
        except KeyboardInterrupt:
            logging.getLogger("a2a-client").info("Stdio mode interrupted")
        except Exception as e:
            logging.getLogger("a2a-client").error(f"Error in stdio mode: {e}")
    
    try:
        asyncio.run(_run_stdio())
    except Exception as e:
        logging.getLogger("a2a-client").error(f"Fatal error in stdio mode: {e}")

# -----------------------------------------------------------------------------
# Script entry‑point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        app()
    except KeyboardInterrupt:
        logging.debug("KeyboardInterrupt received")
    except Exception as exc:
        logging.error("Unhandled exception: %s", exc)
    finally:
        restore_terminal()