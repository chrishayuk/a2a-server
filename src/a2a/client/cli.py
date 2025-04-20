#!/usr/bin/env python3
# a2a/client/cli.py
"""
A2A Client CLI

Provides commands to send, get, cancel, and watch tasks via the A2A server
transports.  Supports a --prefix argument to target different handler mounts
(e.g. “pirate_agent” shorthand).
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
                f"HTTP Request: {request.method} {request.url} "
                f"\"{response.status_code} {response.reason_phrase}\""
            )
            if self.level == logging.DEBUG:
                self.logger.debug("Response headers: %s", response.headers)
                ct = response.headers.get("content-type", "")
                try:
                    if "application/json" in ct:
                        self.logger.debug("Response JSON: %s", response.json())
                    elif "text/event-stream" in ct:
                        self.logger.debug("SSE stream started")
                    else:
                        self.logger.debug("Response body: %.200s", response.text)
                except Exception:
                    self.logger.debug("Response body (unparsed): %.200s", response.text)
            return response
        return on_response

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
def setup_logging(args):
    log_level = logging.DEBUG if args.debug else getattr(logging, args.log_level.upper())
    root_logger = logging.getLogger()
    cli_logger  = logging.getLogger("a2a-client")
    http_logger = logging.getLogger("httpx")
    sse_logger  = logging.getLogger("a2a-client.sse")

    fmt = "%(message)s"
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt))

    # base levels
    root_logger.setLevel(logging.WARNING)
    cli_logger.setLevel(log_level)
    http_logger.setLevel(logging.WARNING if args.quiet else log_level)
    sse_logger.setLevel(logging.WARNING if args.quiet else log_level)

    # clean handlers
    for lg in (root_logger, cli_logger, http_logger, sse_logger):
        lg.handlers.clear()
        lg.addHandler(console)

    # wire HTTPX hook for full request/response dumps
    if args.debug:
        httpx.Client(event_hooks={"response": [HTTPXLogger(logging.DEBUG)]})
        httpx.AsyncClient(event_hooks={"response": [HTTPXLogger(logging.DEBUG)]})

    return cli_logger

# -----------------------------------------------------------------------------
# Defaults for constructing endpoints
# -----------------------------------------------------------------------------
DEFAULT_HOST  = "http://localhost:8000"
RPC_SUFFIX    = "/rpc"
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
    return True

# -----------------------------------------------------------------------------
# Helpers to format and print events & tasks
# -----------------------------------------------------------------------------
def print_status(evt: TaskStatusUpdateEvent):
    state = evt.status.state.value
    msg = ""
    if evt.status.message and evt.status.message.parts:
        msg = f" — {evt.status.message.parts[0].text}"
    print(f"[status] {state}{msg}")

def print_artifact(evt: TaskArtifactUpdateEvent):
    name = evt.artifact.name or "<unnamed>"
    for part in evt.artifact.parts:
        if hasattr(part, "text"):
            print(f"[artifact:{name}] {part.text}")
        else:
            print(f"[artifact:{name}] {json.dumps(part.model_dump())}")

def print_task_info(task, colorize=False):
    print(f"Task ID: {task.id}")
    state = task.status.state.value
    print(f"Status : {state}")
    if task.artifacts:
        print("Artifacts:")
        for art in task.artifacts:
            print(f"  • {art.name or '<unnamed>'}")
            for p in art.parts:
                if getattr(p, "text", None):
                    print(f"    {p.text}")

# -----------------------------------------------------------------------------
# Sub‑command implementations
# -----------------------------------------------------------------------------
def send_task(args):
    base       = resolve_base(args.prefix)
    rpc_url    = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX

    if not asyncio.run(check_server_running(base, args.quiet)):
        sys.exit(1)

    client  = A2AClient.over_http(rpc_url)
    part    = TextPart(type="text", text=args.text)
    message = Message(role="user", parts=[part])
    task_id = str(uuid.uuid4())
    params  = TaskSendParams(id=task_id, sessionId=None, message=message)

    try:
        task = asyncio.run(client.send_task(params))
        if not args.quiet and not args.wait:
            print_task_info(task, args.color)
        if args.debug:
            logging.getLogger("a2a-client").debug(
                "Send response: %s", task.model_dump(by_alias=True)
            )
    except JSONRPCError as exc:
        logging.getLogger("a2a-client").error("Send failed: %s", exc)
        sys.exit(1)
    except httpx.ConnectError:
        logging.getLogger("a2a-client").error("Cannot connect to RPC at %s", rpc_url)
        sys.exit(1)

    # Wait & stream
    if args.wait:
        sse_client = A2AClient.over_sse(rpc_url, events_url)

        async def _stream():
            try:
                async for evt in sse_client.send_subscribe(params):
                    if isinstance(evt, TaskStatusUpdateEvent):
                        print_status(evt)
                    elif isinstance(evt, TaskArtifactUpdateEvent):
                        print_artifact(evt)
                    else:
                        print(json.dumps(evt, indent=2))
                    if isinstance(evt, TaskStatusUpdateEvent) and evt.final:
                        break
            except Exception:
                logging.getLogger("a2a-client").exception("Stream error")
            finally:
                if hasattr(sse_client.transport, "close"):
                    await sse_client.transport.close()

        try:
            asyncio.run(_stream())
        except KeyboardInterrupt:
            if not args.quiet:
                logging.getLogger("a2a-client").info("Stream interrupted")

def get_task(args):
    base    = resolve_base(args.prefix)
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
    except JSONRPCError as exc:
        logging.getLogger("a2a-client").error("Get failed: %s", exc)
        sys.exit(1)
    except httpx.ConnectError:
        logging.getLogger("a2a-client").error("Cannot connect to RPC at %s", rpc_url)
        sys.exit(1)

def cancel_task(args):
    base    = resolve_base(args.prefix)
    rpc_url = base + RPC_SUFFIX

    if not asyncio.run(check_server_running(base, args.quiet)):
        sys.exit(1)

    client = A2AClient.over_http(rpc_url)
    params = TaskIdParams(id=args.id)

    try:
        asyncio.run(client.cancel_task(params))
        logging.getLogger("a2a-client").info("Canceled task %s", args.id)
    except Exception as exc:
        logging.getLogger("a2a-client").error("Cancel failed: %s", exc)
        sys.exit(1)

def watch_task(args):
    base       = resolve_base(args.prefix)
    rpc_url    = base + RPC_SUFFIX
    events_url = base + EVENTS_SUFFIX

    if not asyncio.run(check_server_running(base, args.quiet)):
        sys.exit(1)

    client = A2AClient.over_sse(rpc_url, events_url)

    async def _watch():
        if args.id:
            iterator = client.resubscribe(TaskQueryParams(id=args.id))
        else:
            part    = TextPart(type="text", text=args.text)
            message = Message(role="user", parts=[part])
            params  = TaskSendParams(id=str(uuid.uuid4()), sessionId=None, message=message)
            iterator = client.send_subscribe(params)

        try:
            async for evt in iterator:
                if isinstance(evt, TaskStatusUpdateEvent):
                    print_status(evt)
                elif isinstance(evt, TaskArtifactUpdateEvent):
                    print_artifact(evt)
                else:
                    print(json.dumps(evt, indent=2))
                if isinstance(evt, TaskStatusUpdateEvent) and evt.final:
                    break
        except Exception:
            logging.getLogger("a2a-client").exception("Watch error")
        finally:
            if hasattr(client.transport, "close"):
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
    parser.add_argument("--debug", action="store_true", help="Enable HTTPX wire‑level logging")
    parser.add_argument("--log-level", choices=["debug","info","warning","error"], default="info",
                        help="Client logging level")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress non‑essential output")
    parser.add_argument("--color", action="store_true", help="Colorize output")

    sub = parser.add_subparsers(dest="cmd")

    p_send = sub.add_parser("send", help="Send a text task")
    p_send.add_argument("--prefix", default=None,
                        help="Handler mount or URL (e.g. pirate_agent or http://host:8000/chef_agent)")
    p_send.add_argument("text", help="Text of the task to send")
    p_send.add_argument("--wait", action="store_true", help="Wait and stream status/artifacts")
    p_send.set_defaults(func=send_task)

    p_get = sub.add_parser("get", help="Fetch a task by ID")
    p_get.add_argument("--prefix", default=None, help="Handler mount or URL")
    p_get.add_argument("id", help="Task ID to fetch")
    p_get.add_argument("--json", action="store_true", help="Output full JSON")
    p_get.set_defaults(func=get_task)

    p_cancel = sub.add_parser("cancel", help="Cancel a task")
    p_cancel.add_argument("--prefix", default=None, help="Handler mount or URL")
    p_cancel.add_argument("id", help="Task ID to cancel")
    p_cancel.set_defaults(func=cancel_task)

    p_watch = sub.add_parser("watch", help="Watch task events via SSE")
    p_watch.add_argument("--prefix", default=None, help="Handler mount or URL")
    group = p_watch.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="Existing task ID to watch")
    group.add_argument("--text", help="Text to send and watch new task")
    p_watch.set_defaults(func=watch_task)

    args = parser.parse_args()
    args.color = args.color or sys.stdout.isatty()

    setup_logging(args)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
