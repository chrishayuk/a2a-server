#!/usr/bin/env python3
# a2a/client/cli.py
"""
A2A Client CLI

Provides commands to send, get, cancel, and watch tasks via the A2A server transports.
"""
import argparse
import sys
import uuid
import asyncio
import logging
import os
import json
from typing import Dict, Any, Optional

from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.spec import (
    TextPart,
    Message,
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
)
from a2a.json_rpc.json_rpc_errors import JSONRPCError
import httpx

# -----------------------------------------------------------------------------
# Custom HTTP logger to debug request/response
# -----------------------------------------------------------------------------
class HTTPXLogger:
    def __init__(self, level=logging.DEBUG):
        self.logger = logging.getLogger("httpx")
        self.level = level

    def __call__(self, request):
        async def on_response(response):
            self.logger.log(self.level, f"HTTP Request: {request.method} {request.url} \"{response.status_code} {response.reason_phrase}\"")
            if self.level == logging.DEBUG:
                self.logger.debug(f"Response headers: {response.headers}")
                if 'application/json' in response.headers.get('content-type', ''):
                    try:
                        self.logger.debug(f"Response JSON: {response.json()}")
                    except Exception:
                        self.logger.debug(f"Response body (not JSON): {response.text[:200]}...")
                elif 'text/event-stream' in response.headers.get('content-type', ''):
                    self.logger.debug("SSE stream started")
                else:
                    self.logger.debug(f"Response body: {response.text[:200]}...")
            return response
        return on_response

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
def setup_logging(args):
    # Determine log level
    log_level = logging.DEBUG if args.debug else getattr(logging, args.log_level.upper())
    
    # Set up different loggers with their own levels
    root_logger = logging.getLogger()
    cli_logger = logging.getLogger("a2a-client")
    http_logger = logging.getLogger("httpx")
    sse_logger = logging.getLogger("a2a-client.sse")
    
    # Configure formatters
    if args.quiet:
        cli_formatter = logging.Formatter("%(message)s")
    else:
        cli_formatter = logging.Formatter("%(message)s")
    
    debug_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    
    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(cli_formatter)
    
    # Set up log file if requested
    log_dir = os.environ.get("A2A_LOG_DIR")
    file_handler = None
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "a2a-client.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(debug_formatter)
        file_handler.setLevel(logging.DEBUG)  # Always debug level for file logs
    
    # Configure logger levels
    root_logger.setLevel(logging.WARNING)  # Limit third-party logs
    cli_logger.setLevel(log_level)
    
    # In quiet mode, only show warnings and errors for HTTP logs
    http_logger.setLevel(logging.WARNING if args.quiet else log_level)
    sse_logger.setLevel(logging.WARNING if args.quiet else log_level)
    
    # Clear existing handlers to avoid duplicates
    root_logger.handlers = []
    cli_logger.handlers = []
    http_logger.handlers = []
    sse_logger.handlers = []
    
    # Add handlers to loggers
    cli_logger.addHandler(console_handler)
    http_logger.addHandler(console_handler)
    sse_logger.addHandler(console_handler)
    
    if file_handler:
        cli_logger.addHandler(file_handler)
        http_logger.addHandler(file_handler)
        sse_logger.addHandler(file_handler)
    
    # Configure HTTP client logging only for debug mode
    hooks_level = logging.DEBUG if log_level <= logging.DEBUG else None
    if hooks_level:
        httpx.Client(event_hooks={'response': [HTTPXLogger(level=hooks_level)]})
        httpx.AsyncClient(event_hooks={'response': [HTTPXLogger(level=hooks_level)]})
    
    return cli_logger

logger = logging.getLogger("a2a-client")

DEFAULT_RPC_ENDPOINT = "http://localhost:8000/rpc"
DEFAULT_EVENTS_ENDPOINT = "http://localhost:8000/events"


# -----------------------------------------------------------------------------
# Connection Validation
# -----------------------------------------------------------------------------

async def check_server_running(endpoint, quiet=False):
    """Verify server is running before making requests."""
    base_url = endpoint.rsplit("/", 1)[0]  # Remove "/rpc" to get base URL
    client = httpx.AsyncClient()
    try:
        await client.get(base_url, timeout=3.0)
    except httpx.ConnectError:
        if not quiet:
            logger.error(f"Cannot connect to A2A server at {base_url}")
            logger.error("Please ensure the server is running with: a2a-server --host 0.0.0.0 --port 8000")
        return False
    except Exception as e:
        if not quiet:
            logger.warning(f"Could not verify server availability: {e}")
    finally:
        await client.aclose()
    return True


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def format_event(evt, colorize=False):
    """Format an event for display regardless of its structure."""
    # ANSI color codes
    RESET = "\033[0m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    
    # Apply colors based on event type if colorize is enabled
    start_color = ""
    end_color = ""
    
    # Handle raw dict events from the server
    if isinstance(evt, dict):
        # Format status update events
        if "status" in evt:
            state = evt["status"].get("state", "unknown")
            task_id = evt.get("id", "unknown")
            is_final = evt.get("final", False)
            
            if colorize:
                if is_final:
                    start_color = GREEN
                else:
                    start_color = BLUE
                end_color = RESET
                
            return f"{start_color}Status: {state}{' (FINAL)' if is_final else ''}{end_color}"
        
        # Format artifact events
        elif "artifact" in evt:
            task_id = evt.get("id", "unknown")
            artifact = evt["artifact"]
            name = artifact.get("name", "<unknown>")
            
            # Extract text from parts if available
            parts_text = ""
            for part in artifact.get("parts", []):
                if isinstance(part, dict) and "text" in part:
                    parts_text = f"\n{part['text']}"
            
            if colorize:
                start_color = CYAN
                end_color = RESET
                
            return f"{start_color}Artifact: {name}{end_color}{parts_text}"
        
        # Generic handling for other dict formats
        else:
            if colorize:
                start_color = YELLOW
                end_color = RESET
                
            return f"{start_color}Event: {json.dumps(evt, indent=2)}{end_color}"
    
    # Handle Pydantic model events
    elif hasattr(evt, "model_dump"):
        try:
            return format_event(evt.model_dump(), colorize)
        except Exception:
            return f"Event: {evt}"
    
    # Fallback for any other type
    else:
        return f"Event: {evt}"


# -----------------------------------------------------------------------------
# Output Functions
# -----------------------------------------------------------------------------

def print_task_info(task, colorize=False):
    """Print formatted task information"""
    RESET = "\033[0m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    
    if colorize:
        print(f"\n{GREEN}Task ID:{RESET} {task.id}")
        print(f"{GREEN}Status:{RESET} {task.status.state}")
        
        if task.artifacts:
            print(f"\n{CYAN}Artifacts:{RESET}")
            for artifact in task.artifacts:
                print(f"  {CYAN}• {artifact.name}{RESET}")
                for part in artifact.parts:
                    if hasattr(part, "text") and part.text:
                        print(f"    {part.text}")
    else:
        print(f"\nTask ID: {task.id}")
        print(f"Status: {task.status.state}")
        
        if task.artifacts:
            print("\nArtifacts:")
            for artifact in task.artifacts:
                print(f"  • {artifact.name}")
                for part in artifact.parts:
                    if hasattr(part, "text") and part.text:
                        print(f"    {part.text}")


# -----------------------------------------------------------------------------
# Subcommands
# -----------------------------------------------------------------------------

def send_task(args):
    """
    Send a new task to the A2A server and optionally wait for its completion.
    """
    # Verify server is running first
    if not asyncio.run(check_server_running(args.rpc, args.quiet)):
        sys.exit(1)
        
    # Build the client + params
    rpc_client = A2AClient.over_http(args.rpc)
    part = TextPart(type="text", text=args.text)
    message = Message(role="user", parts=[part])
    task_id = str(uuid.uuid4())
    params = TaskSendParams(id=task_id, sessionId=None, message=message)

    try:
        # First, submit the task
        task = asyncio.run(rpc_client.send_task(params))
        
        if not args.quiet:
            if args.wait:
                if args.debug:
                    logger.info(f"Task submitted. ID: {task.id}")
            else:
                print_task_info(task, args.color)
        
        # Debug: Show full task response
        if args.debug:
            logger.debug(f"Task response: {task.model_dump(by_alias=True)}")
            
    except JSONRPCError as e:
        logger.error(f"Failed to send task: {e}")
        sys.exit(1)
    except httpx.ConnectError:
        logger.error(f"Cannot connect to A2A server at {args.rpc}")
        logger.error("Please ensure the server is running with: a2a-server --host 0.0.0.0 --port 8000")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

    # If --wait was passed, open an SSE stream for events
    if args.wait:
        try:
            sse_client = A2AClient.over_sse(args.rpc, args.events)
        except Exception as e:
            logger.error(f"Failed to create SSE client: {e}")
            logger.error("Continuing without waiting for events")
            return

        async def _stream_events():
            try:
                # stream status/artifacts for this new task
                event_params = TaskSendParams(id=task_id, sessionId=None, message=message)
                logger.debug(f"Subscribing to events for task {task.id}")
                
                found_final = False
                artifact_content = None
                
                try:
                    async for evt in sse_client.send_subscribe(event_params):
                        # In quiet mode, just collect the artifact content
                        if args.quiet:
                            if isinstance(evt, dict) and "artifact" in evt:
                                for part in evt["artifact"].get("parts", []):
                                    if isinstance(part, dict) and "text" in part:
                                        artifact_content = part["text"]
                            
                            # On final state, print just the artifact content and exit
                            if isinstance(evt, dict) and evt.get("final", False) and "status" in evt:
                                if artifact_content:
                                    print(artifact_content)
                                found_final = True
                                break
                        else:
                            # Normal mode - print formatted events
                            formatted = format_event(evt, args.color)
                            print(formatted)
                            
                            # Debug raw event data if requested
                            if args.debug:
                                logger.debug(f"Raw event data: {evt}")
                            
                            # Stop on final state
                            if isinstance(evt, dict) and evt.get("final", False) and "status" in evt:
                                found_final = True
                                break
                finally:
                    # Ensure proper client closure
                    if sse_client.transport and hasattr(sse_client.transport, 'close'):
                        await sse_client.transport.close()
                        
                # If no final event was found, log completion anyway
                if not found_final and not args.quiet and args.debug:
                    logger.info(f"Finished streaming events for task {task.id}")
                    
            except JSONRPCError as e:
                logger.error(f"Stream error: {e}")
            except httpx.ConnectError:
                logger.error(f"Cannot connect to SSE endpoint at {args.events}")
                logger.error("Please ensure the server is running with events enabled")
            except Exception as e:
                logger.error(f"Error during event streaming: {e}")
                logger.debug("Exception details:", exc_info=True if args.debug else False)

        try:
            asyncio.run(_stream_events())
        except KeyboardInterrupt:
            if not args.quiet:
                logger.info("Event streaming interrupted by user")


def get_task(args):
    """Fetch and display a task by ID."""
    if not asyncio.run(check_server_running(args.rpc, args.quiet)):
        sys.exit(1)
        
    client = A2AClient.over_http(args.rpc)
    params = TaskQueryParams(id=args.id)

    try:
        task = asyncio.run(client.get_task(params))
        
        if args.json:
            print(task.model_dump_json(indent=2, by_alias=True))
        else:
            print_task_info(task, args.color)
            
    except JSONRPCError as e:
        logger.error(f"Failed to fetch task {args.id}: {e}")
        sys.exit(1)
    except httpx.ConnectError:
        logger.error(f"Cannot connect to A2A server at {args.rpc}")
        logger.error("Please ensure the server is running with: a2a-server --host 0.0.0.0 --port 8000")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cancel_task(args):
    """Cancel a task by ID."""
    if not asyncio.run(check_server_running(args.rpc, args.quiet)):
        sys.exit(1)
        
    client = A2AClient.over_http(args.rpc)
    params = TaskIdParams(id=args.id)

    try:
        asyncio.run(client.cancel_task(params))
        logger.info(f"Task {args.id} canceled.")
    except JSONRPCError as e:
        logger.error(f"Failed to cancel task {args.id}: {e}")
        sys.exit(1)
    except httpx.ConnectError:
        logger.error(f"Cannot connect to A2A server at {args.rpc}")
        logger.error("Please ensure the server is running with: a2a-server --host 0.0.0.0 --port 8000")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def watch_task(args):
    """Watch status and artifact events for a given task (existing or new)."""
    if not asyncio.run(check_server_running(args.rpc, args.quiet)):
        sys.exit(1)
        
    client = A2AClient.over_sse(args.rpc, args.events)

    async def _watch():
        try:
            found_final = False
            iterator = None
            artifact_content = None
            
            try:
                if args.id:
                    # resubscribe to an existing task
                    query = TaskQueryParams(id=args.id)
                    iterator = client.resubscribe(query)
                    if not args.quiet and args.debug:
                        logger.info(f"Resubscribing to task {args.id}")
                else:
                    # send-and-watch a fresh prompt
                    part = TextPart(type="text", text=args.text)
                    message = Message(role="user", parts=[part])
                    params = TaskSendParams(id=str(uuid.uuid4()), sessionId=None, message=message)
                    iterator = client.send_subscribe(params)
                    if not args.quiet and args.debug:
                        logger.info(f"Subscribed to new task events (prompt: '{args.text}')")

                async for evt in iterator:
                    # In quiet mode, just collect the artifact content
                    if args.quiet:
                        if isinstance(evt, dict) and "artifact" in evt:
                            for part in evt["artifact"].get("parts", []):
                                if isinstance(part, dict) and "text" in part:
                                    artifact_content = part["text"]
                        
                        # On final state, print just the artifact content and exit
                        if isinstance(evt, dict) and evt.get("final", False) and "status" in evt:
                            if artifact_content:
                                print(artifact_content)
                            found_final = True
                            break
                    else:
                        # Normal mode - print formatted events
                        formatted = format_event(evt, args.color)
                        print(formatted)
                        
                        # Debug raw event data if requested
                        if args.debug:
                            logger.debug(f"Raw event data: {evt}")
                        
                        # Stop on final state
                        if isinstance(evt, dict) and evt.get("final", False) and "status" in evt:
                            found_final = True
                            break
            finally:
                # Ensure proper client closure
                if client.transport and hasattr(client.transport, 'close'):
                    await client.transport.close()
                
            # If no final event was found, log completion anyway
            if not found_final and iterator is not None and not args.quiet and args.debug:
                logger.info("Finished streaming events")
                
        except JSONRPCError as e:
            logger.error(f"Watch error: {e}")
        except httpx.ConnectError:
            logger.error(f"Cannot connect to SSE endpoint at {args.events}")
            logger.error("Please ensure the server is running with events enabled")
        except Exception as e:
            logger.error(f"Error during task watching: {e}")
            logger.debug("Exception details:", exc_info=True if args.debug else False)

    try:
        asyncio.run(_watch())
    except KeyboardInterrupt:
        if not args.quiet:
            logger.info("Stopped watching.")


# -----------------------------------------------------------------------------
# CLI wiring
# -----------------------------------------------------------------------------

def main():
    # Create a parent parser for common arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--color", action="store_true", help="Enable colorized output")
    
    # Main parser
    parser = argparse.ArgumentParser(prog="a2a-client")
    parser.add_argument("--rpc", default=DEFAULT_RPC_ENDPOINT, help="RPC endpoint URL")
    parser.add_argument("--events", default=DEFAULT_EVENTS_ENDPOINT,
                        help="SSE events URL (for --wait / watch)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"],
                        default="info", help="Set logging level")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Minimize output (useful for scripting)")
    parser.add_argument("--color", action="store_true", 
                        help="Enable colorized output")
    
    sub = parser.add_subparsers(dest="cmd")

    # send (include parent parser for shared args)
    p_send = sub.add_parser("send", help="Send a text task", parents=[parent_parser])
    p_send.add_argument("text", help="Text of the task to send")
    p_send.add_argument(
        "--wait",
        action="store_true",
        help="After sending, stream its status/artifact events until completion"
    )
    p_send.set_defaults(func=send_task)

    # get
    p_get = sub.add_parser("get", help="Get a task by ID", parents=[parent_parser])
    p_get.add_argument("id", help="Task ID to fetch")
    p_get.add_argument("--json", action="store_true", help="Output full JSON response")
    p_get.set_defaults(func=get_task)

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel a task by ID", parents=[parent_parser])
    p_cancel.add_argument("id", help="Task ID to cancel")
    p_cancel.set_defaults(func=cancel_task)

    # watch
    p_watch = sub.add_parser("watch", help="Watch task events via SSE", parents=[parent_parser])
    group = p_watch.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="Existing Task ID to watch")
    group.add_argument("--text", help="Prompt text to send‑and‑watch a new task")
    p_watch.set_defaults(func=watch_task)

    args = parser.parse_args()
    
    # Handle color output - use isatty to auto-detect terminal
    if args.color is None:
        args.color = sys.stdout.isatty()
    
    # Set up logging based on args
    global logger
    logger = setup_logging(args)
    
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()