#!/usr/bin/env python3
# a2a/client/cli.py
"""
A2A Client CLI

Provides a rich, interactive command-line interface for the Agent-to-Agent protocol.
Includes commands to send, get, cancel, and watch tasks via various A2A transports.
"""
import sys
import uuid
import asyncio
import logging
import json
import os
import signal
import atexit
from typing import Optional, Any, Dict

import typer
from rich import print
from rich.console import Console
from rich.panel import Panel

from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.spec import (
    TextPart, Message,
    TaskSendParams, TaskQueryParams, TaskIdParams,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent,
)
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.client.transport.stdio import JSONRPCStdioTransport
from a2a.client.chat.chat_handler import handle_chat_mode
from a2a.client.ui.ui_helpers import display_task_info, restore_terminal, clear_screen

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
def setup_logging(args) -> logging.Logger:
    """
    Configure logging so that by default only errors are shown,
    unless --debug or a more verbose --log-level is requested.
    """
    # Determine desired level
    if args.debug:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.ERROR
    elif args.log_level.upper() not in ("INFO",):
        level = getattr(logging, args.log_level.upper(), logging.ERROR)
    else:
        # default “clean” mode: show only errors
        level = logging.ERROR

    # Root logger: only errors
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.ERROR)

    # CLI logger
    cli_logger = logging.getLogger("a2a-client")
    cli_logger.setLevel(level)

    # HTTPX logger (if present)
    http_logger = logging.getLogger("httpx") if "httpx" in sys.modules else None
    if http_logger:
        http_logger.setLevel(logging.WARNING if args.quiet else level)

    # SSE logger
    sse_logger = logging.getLogger("a2a-client.sse")
    sse_logger.setLevel(logging.WARNING if args.quiet else level)

    # Formatter: include timestamps only in debug
    fmt = "%(asctime)s - %(levelname)s - %(message)s" if args.debug else "%(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))

    # Clear existing handlers and attach our handler
    for lg in [root_logger, cli_logger, sse_logger] + ([http_logger] if http_logger else []):
        lg.handlers.clear()
        lg.addHandler(handler)

    return cli_logger


# -----------------------------------------------------------------------------
DEFAULT_HOST = "http://localhost:8000"
RPC_SUFFIX = "/rpc"
EVENTS_SUFFIX = "/events"

def resolve_base(prefix: Optional[str]) -> str:
    if prefix and prefix.startswith(("http://", "https://")):
        return prefix.rstrip("/")
    if prefix:
        return f"{DEFAULT_HOST.rstrip('/')}/{prefix.strip('/')}"
    return DEFAULT_HOST

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

def restore_and_exit(signum=None, frame=None):
    """Clean up and exit on signal."""
    restore_terminal()
    sys.exit(0)

atexit.register(restore_terminal)
signal.signal(signal.SIGINT, restore_and_exit)
signal.signal(signal.SIGTERM, restore_and_exit)
if hasattr(signal, "SIGQUIT"):
    signal.signal(signal.SIGQUIT, restore_and_exit)

# -----------------------------------------------------------------------------
app = typer.Typer(help="A2A Client CLI - Interactive client for the Agent-to-Agent protocol")

@app.callback(invoke_without_command=True)
def common_options(
    ctx: typer.Context,
    config_file: str = typer.Option("~/.a2a/config.json", help="Path to config file"),
    server: str = typer.Option(None, help="Server URL or name from config"),
    debug: bool = typer.Option(False, help="Enable debug logging"),
    quiet: bool = typer.Option(False, help="Suppress non-essential output"),
    log_level: str = typer.Option("INFO", help="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL"),
):
    """
    Common options: config file, server, debug, quiet, log-level.
    If no subcommand is given, launches interactive chat mode.
    """
    # Validate log level
    if not isinstance(getattr(logging, log_level.upper(), None), int):
        typer.echo(f"Invalid log level: {log_level}")
        raise typer.Exit(1)

    class Args: pass
    args = Args()
    args.debug = debug
    args.quiet = quiet
    args.log_level = log_level
    setup_logging(args)

    expanded = os.path.expanduser(config_file)
    base_url = None
    if server:
        if server.startswith(("http://", "https://")):
            base_url = server
        else:
            # Try lookup in config
            if os.path.exists(expanded):
                cfg = json.load(open(expanded))
                base_url = cfg.get("servers", {}).get(server)
            if not base_url:
                base_url = resolve_base(server)

    ctx.obj = {"config_file": expanded, "base_url": base_url, "debug": debug, "quiet": quiet}

    if ctx.invoked_subcommand is None:
        try:
            asyncio.run(handle_chat_mode(base_url, expanded))
        finally:
            restore_terminal()
        raise typer.Exit()

# -----------------------------------------------------------------------------
@app.command()
def send(
    text: str = typer.Argument(..., help="Text of the task to send"),
    prefix: Optional[str] = typer.Option(None, help="Handler mount or URL"),
    wait: bool = typer.Option(False, help="Wait and stream status/artifacts"),
    color: bool = typer.Option(True, help="Colorize output"),
):
    """Send a text task to the A2A server and optionally wait for results."""
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX
    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    client = A2AClient.over_http(rpc_url)
    task_id = str(uuid.uuid4())
    params = TaskSendParams(
        id=task_id,
        sessionId=None,
        message=Message(role="user", parts=[TextPart(type="text", text=text)])
    )

    try:
        task = asyncio.run(client.send_task(params))
        if not wait:
            display_task_info(task, color)
        logging.getLogger("a2a-client").debug(
            "Send response: %s", json.dumps(task.model_dump(by_alias=True), indent=2)
        )
    except JSONRPCError as exc:
        logging.getLogger("a2a-client").error("Send failed: %s", exc)
        raise typer.Exit(1)

    if wait:
        sse_client = A2AClient.over_sse(rpc_url, events_url)
        async def _stream():
            from rich.live import Live
            from rich.text import Text
            from a2a.client.ui.ui_helpers import format_status_event, format_artifact_event
            console = Console()
            with Live("", refresh_per_second=4, console=console) as live:
                async for evt in sse_client.send_subscribe(params):
                    if isinstance(evt, TaskStatusUpdateEvent):
                        live.update(Text.from_markup(format_status_event(evt)))
                    elif isinstance(evt, TaskArtifactUpdateEvent):
                        live.update(Text.from_markup(format_artifact_event(evt)))
        asyncio.run(_stream())

# -----------------------------------------------------------------------------
@app.command()
def get(
    id: str = typer.Argument(..., help="Task ID to fetch"),
    prefix: Optional[str] = typer.Option(None, help="Handler mount or URL"),
    json_output: bool = typer.Option(False, "--json", help="Output full JSON"),
    color: bool = typer.Option(True, help="Colorize output"),
):
    """Fetch a task by ID."""
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX
    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    client = A2AClient.over_http(rpc_url)
    task = asyncio.run(client.get_task(TaskQueryParams(id=id)))
    if json_output:
        Console().print(json.dumps(task.model_dump(by_alias=True), indent=2))
    else:
        display_task_info(task, color)

# -----------------------------------------------------------------------------
@app.command()
def cancel(
    id: str = typer.Argument(..., help="Task ID to cancel"),
    prefix: Optional[str] = typer.Option(None, help="Handler mount or URL"),
):
    """Cancel a task by ID."""
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX
    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    asyncio.run(A2AClient.over_http(rpc_url).cancel_task(TaskIdParams(id=id)))
    Console().print(f"[green]Canceled task {id}[/green]")

# -----------------------------------------------------------------------------
@app.command()
def watch(
    id: Optional[str] = typer.Argument(None, help="Task ID to watch"),
    text: Optional[str] = typer.Option(None, help="Text to send and watch new task"),
    prefix: Optional[str] = typer.Option(None, help="Handler mount or URL"),
):
    """Watch task events via SSE."""
    base = resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX
    if not asyncio.run(check_server_running(base, quiet=False)):
        raise typer.Exit(1)

    client = A2AClient.over_sse(rpc_url, events_url)
    from rich.live import Live
    from rich.text import Text
    from a2a.client.ui.ui_helpers import format_status_event, format_artifact_event

    if text:
        params = TaskSendParams(
            id=str(uuid.uuid4()), sessionId=None,
            message=Message(role="user", parts=[TextPart(type="text", text=text)])
        )
        stream = client.send_subscribe(params)
    elif id:
        stream = client.resubscribe(TaskQueryParams(id=id))
    else:
        print("[red]Error: specify --id or --text[/red]")
        return

    async def _watch():
        console = Console()
        with Live("", refresh_per_second=4, console=console) as live:
            async for evt in stream:
                if isinstance(evt, TaskStatusUpdateEvent):
                    live.update(Text.from_markup(format_status_event(evt)))
                elif isinstance(evt, TaskArtifactUpdateEvent):
                    live.update(Text.from_markup(format_artifact_event(evt)))
    asyncio.run(_watch())

# -----------------------------------------------------------------------------
@app.command()
def chat(
    config_file: str = typer.Option("~/.a2a/config.json", help="Path to config file"),
    server: str = typer.Option(None, help="Server URL or name"),
):
    """Start interactive chat mode."""
    expanded = os.path.expanduser(config_file)
    base = server if server and server.startswith(("http://","https://")) else None
    asyncio.run(handle_chat_mode(base, expanded))
    restore_terminal()

# -----------------------------------------------------------------------------
@app.command()
def stdio():
    """Run in stdio mode (JSON-RPC over stdin/stdout)."""
    client = A2AClient.over_stdio()

    async def _run_stdio():
        async for message in client.transport.stream():
            # handle JSON-RPC requests here...
            pass

    asyncio.run(_run_stdio())

# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        app()
    except KeyboardInterrupt:
        logging.getLogger("a2a-client").debug("Interrupted by user")
    finally:
        restore_terminal()
