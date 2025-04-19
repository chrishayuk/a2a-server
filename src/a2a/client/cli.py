#!/usr/bin/env python3
# a2a/client/cli.py
"""
A2A Client CLI

Provides commands to send, get, cancel, and watch tasks via the A2A server transports.
Supports a --prefix argument to target different handler mounts (e.g. pirate_agent shorthand).
"""
import argparse
import sys
import uuid
import asyncio
import logging
import json
from typing import Optional

import httpx
from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.spec import TextPart, Message, TaskSendParams, TaskQueryParams, TaskIdParams
from a2a.json_rpc.json_rpc_errors import JSONRPCError

# -----------------------------------------------------------------------------
# Custom HTTP logger to debug request/response
# -----------------------------------------------------------------------------
class HTTPXLogger:
    def __init__(self, level=logging.DEBUG):
        self.logger = logging.getLogger("httpx")
        self.level = level

    def __call__(self, request):
        async def on_response(response):
            self.logger.log(
                self.level,
                f"HTTP Request: {request.method} {request.url} \"{response.status_code} {response.reason_phrase}\""
            )
            if self.level == logging.DEBUG:
                self.logger.debug(f"Response headers: {response.headers}")
                ct = response.headers.get('content-type', '')
                if 'application/json' in ct:
                    try:
                        self.logger.debug(f"Response JSON: {response.json()}")
                    except Exception:
                        self.logger.debug(f"Response body (not JSON): {response.text[:200]}...")
                elif 'text/event-stream' in ct:
                    self.logger.debug("SSE stream started")
                else:
                    self.logger.debug(f"Response body: {response.text[:200]}...")
            return response
        return on_response

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
def setup_logging(args):
    log_level = logging.DEBUG if args.debug else getattr(logging, args.log_level.upper())
    root_logger = logging.getLogger()
    cli_logger = logging.getLogger("a2a-client")
    http_logger = logging.getLogger("httpx")
    sse_logger = logging.getLogger("a2a-client.sse")

    fmt = "%(message)s"
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt))

    root_logger.setLevel(logging.WARNING)
    cli_logger.setLevel(log_level)
    http_logger.setLevel(logging.WARNING if args.quiet else log_level)
    sse_logger.setLevel(logging.WARNING if args.quiet else log_level)

    root_logger.handlers = []
    cli_logger.handlers = []
    http_logger.handlers = []
    sse_logger.handlers = []

    cli_logger.addHandler(console)
    http_logger.addHandler(console)
    sse_logger.addHandler(console)

    if args.debug:
        httpx.Client(event_hooks={'response': [HTTPXLogger(level=logging.DEBUG)]})
        httpx.AsyncClient(event_hooks={'response': [HTTPXLogger(level=logging.DEBUG)]})

    return cli_logger

# -----------------------------------------------------------------------------
# Defaults for constructing endpoints
# -----------------------------------------------------------------------------
DEFAULT_HOST = 'http://localhost:8000'
RPC_SUFFIX = '/rpc'
EVENTS_SUFFIX = '/events'

# -----------------------------------------------------------------------------
# Helper to resolve base URL from prefix or shorthand
# -----------------------------------------------------------------------------
def resolve_base(prefix: Optional[str]) -> str:
    if prefix:
        if prefix.startswith('http://') or prefix.startswith('https://'):
            return prefix.rstrip('/')
        return f"{DEFAULT_HOST.rstrip('/')}/{prefix.strip('/')}"
    return DEFAULT_HOST

# -----------------------------------------------------------------------------
# Connection Validation
# -----------------------------------------------------------------------------
async def check_server_running(base_url: str, quiet: bool=False) -> bool:
    client = httpx.AsyncClient()
    try:
        await client.get(base_url, timeout=3.0)
    except httpx.ConnectError:
        if not quiet:
            logging.getLogger("a2a-client").error(f"Cannot connect to A2A server at {base_url}")
        return False
    except Exception as e:
        if not quiet:
            logging.getLogger("a2a-client").warning(f"Server check warning: {e}")
    finally:
        await client.aclose()
    return True

# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------
def format_event(evt, colorize=False):
    if hasattr(evt, 'model_dump'):
        evt = evt.model_dump(exclude_none=True)
    return json.dumps(evt) if isinstance(evt, dict) else str(evt)


def print_task_info(task, colorize=False):
    print(f"Task ID: {task.id}")
    print(f"Status: {task.status.state}")
    if task.artifacts:
        print("Artifacts:")
        for art in task.artifacts:
            print(f"  • {art.name}")
            for p in art.parts:
                if hasattr(p, 'text') and p.text:
                    print(f"    {p.text}")

# -----------------------------------------------------------------------------
# Subcommand implementations
# -----------------------------------------------------------------------------
def send_task(args):
    base = resolve_base(args.prefix)
    rpc_url = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX

    if not asyncio.run(check_server_running(base, args.quiet)):
        sys.exit(1)

    client = A2AClient.over_http(rpc_url)
    part = TextPart(type="text", text=args.text)
    message = Message(role="user", parts=[part])
    task_id = str(uuid.uuid4())
    params = TaskSendParams(id=task_id, sessionId=None, message=message)

    try:
        task = asyncio.run(client.send_task(params))
        if not args.quiet and not args.wait:
            print_task_info(task, args.color)
        if args.debug:
            logging.getLogger("a2a-client").debug(f"Send response: {task.model_dump(by_alias=True)}")
    except JSONRPCError as e:
        logging.getLogger("a2a-client").error(f"Send failed: {e}")
        sys.exit(1)
    except httpx.ConnectError:
        logging.getLogger("a2a-client").error(f"Cannot connect to RPC at {rpc_url}")
        sys.exit(1)

    if args.wait:
        sse = A2AClient.over_sse(rpc_url, events_url)
        async def _stream():
            try:
                async for evt in sse.send_subscribe(params):
                    print(format_event(evt, args.color))
                    if isinstance(evt, dict) and evt.get('final') and 'status' in evt:
                        break
            except Exception as e:
                logging.getLogger("a2a-client").error(f"Stream error: {e}")
            finally:
                if hasattr(sse.transport, 'close'):
                    await sse.transport.close()
        try:
            asyncio.run(_stream())
        except KeyboardInterrupt:
            if not args.quiet:
                logging.getLogger("a2a-client").info("Stream interrupted")


def get_task(args):
    base = resolve_base(args.prefix)
    rpc_url = base + RPC_SUFFIX
    if not asyncio.run(check_server_running(base, args.quiet)):
        sys.exit(1)

    client = A2AClient.over_http(rpc_url)
    params = TaskQueryParams(id=args.id)
    try:
        task = asyncio.run(client.get_task(params))
        if args.json:
            print(task.model_dump_json(indent=2, by_alias=True))
        else:
            print_task_info(task, args.color)
    except JSONRPCError as e:
        logging.getLogger("a2a-client").error(f"Get failed: {e}")
        sys.exit(1)
    except httpx.ConnectError:
        logging.getLogger("a2a-client").error(f"Cannot connect to RPC at {rpc_url}")
        sys.exit(1)


def cancel_task(args):
    base = resolve_base(args.prefix)
    rpc_url = base + RPC_SUFFIX
    if not asyncio.run(check_server_running(base, args.quiet)):
        sys.exit(1)

    client = A2AClient.over_http(rpc_url)
    params = TaskIdParams(id=args.id)
    try:
        asyncio.run(client.cancel_task(params))
        logging.getLogger("a2a-client").info(f"Canceled task {args.id}")
    except Exception as e:
        logging.getLogger("a2a-client").error(f"Cancel failed: {e}")
        sys.exit(1)


def watch_task(args):
    base = resolve_base(args.prefix)
    rpc_url = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX
    if not asyncio.run(check_server_running(base, args.quiet)):
        sys.exit(1)

    client = A2AClient.over_sse(rpc_url, events_url)
    async def _watch():
        if args.id:
            iterator = client.resubscribe(TaskQueryParams(id=args.id))
        else:
            part = TextPart(type="text", text=args.text)
            message = Message(role="user", parts=[part])
            iterator = client.send_subscribe(
                TaskSendParams(id=str(uuid.uuid4()), sessionId=None, message=message)
            )
        try:
            async for evt in iterator:
                print(format_event(evt, args.color))
                if isinstance(evt, dict) and evt.get('final') and 'status' in evt:
                    break
        except Exception as e:
            logging.getLogger("a2a-client").error(f"Watch error: {e}")
        finally:
            if hasattr(client.transport, 'close'):
                await client.transport.close()
    try:
        asyncio.run(_watch())
    except KeyboardInterrupt:
        if not args.quiet:
            logging.getLogger("a2a-client").info("Watch interrupted")

# -----------------------------------------------------------------------------
# CLI wiring
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(prog="a2a-client")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--log-level", choices=["debug","info","warning","error"], default="info",
                        help="Logging level")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet output")
    parser.add_argument("--color", action="store_true", help="Colorize output")

    sub = parser.add_subparsers(dest="cmd")

    p_send = sub.add_parser("send", help="Send a text task")
    p_send.add_argument("--prefix", default=None,
                        help="Handler mount shorthand or full URL (e.g. pirate_agent or http://host:8000/chef_agent)")
    p_send.add_argument("text", help="Text of the task to send")
    p_send.add_argument("--wait", action="store_true", help="Wait and stream status/artifacts")
    p_send.set_defaults(func=send_task)

    p_get = sub.add_parser("get", help="Fetch a task by ID")
    p_get.add_argument("--prefix", default=None,
                       help="Handler mount shorthand or full URL (e.g. pirate_agent or http://host:8000/chef_agent)")
    p_get.add_argument("id", help="Task ID to fetch")
    p_get.add_argument("--json", action="store_true", help="Output full JSON")
    p_get.set_defaults(func=get_task)

    p_cancel = sub.add_parser("cancel", help="Cancel a task")
    p_cancel.add_argument("--prefix", default=None,
                          help="Handler mount shorthand or full URL (e.g. pirate_agent or http://host:8000/chef_agent)")
    p_cancel.add_argument("id", help="Task ID to cancel")
    p_cancel.set_defaults(func=cancel_task)

    p_watch = sub.add_parser("watch", help="Watch task events via SSE")
    p_watch.add_argument("--prefix", default=None,
                         help="Handler mount shorthand or full URL (e.g. pirate_agent or http://host:8000/chef_agent)")
    group = p_watch.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="Existing task ID to watch")
    group.add_argument("--text", help="Text to send and watch new task")
    p_watch.set_defaults(func=watch_task)

    args = parser.parse_args()
    args.color = args.color or sys.stdout.isatty()
    global logger
    logger = setup_logging(args)

    if not hasattr(args, 'func'):
        parser.print_help()
        sys.exit(1)
    args.func(args)
    
if __name__ == '__main__':
    main()
