#!/usr/bin/env python3
# a2a/server/cli.py
"""
Command-line entrypoint to launch the A2A server with HTTP, WS, and SSE transports.
Supports optional stdio mode for CLI-based agents, and a configurable log level.
"""
import sys
import argparse
import logging
import uvicorn
from fastapi import FastAPI

from a2a.server.app import create_app
from a2a.server.transport.stdio import handle_stdio_message
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.pubsub import EventBus
from a2a.server.tasks.task_manager import TaskManager
from a2a.server.methods import register_methods


def main():
    parser = argparse.ArgumentParser(prog="a2a-server")
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run in stdio JSON-RPC mode (reads from stdin, writes to stdout)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP server"
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Logging level"
    )
    args = parser.parse_args()

    # Configure root logger
    numeric_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.stdio:
        # In stdio mode, we run our JSON-RPC loop on stdin/stdout
        event_bus = EventBus()
        manager = TaskManager(event_bus)
        protocol = JSONRPCProtocol()
        register_methods(protocol, manager)

        logging.info("Starting A2A server in stdio mode (log level=%s)", args.log_level)
        for line in sys.stdin:
            resp = handle_stdio_message(protocol, line)
            if resp:
                print(resp, flush=True)

    else:
        # Launch FastAPI app via Uvicorn
        app: FastAPI = create_app()
        logging.info(
            "Starting A2A HTTP server on %s:%d (log level=%s)",
            args.host, args.port, args.log_level
        )
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level=args.log_level
        )


if __name__ == "__main__":
    main()
