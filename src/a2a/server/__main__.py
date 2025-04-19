#!/usr/bin/env python3
# a2a/server/__main__.py
"""
Command-line entrypoint to launch the A2A server with HTTP, WS, and SSE transports.
Supports optional stdio mode for CLI-based agents, and a configurable log level.
"""
import sys
import os
import argparse
import logging
import uvicorn
from fastapi import FastAPI

from a2a.server.logging import configure_logging
from a2a.server.app import create_app
from a2a.server.transport.stdio import handle_stdio_message
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.pubsub import EventBus
from a2a.server.tasks.task_manager import TaskManager
from a2a.server.methods import register_methods
from a2a.server.tasks.discovery import register_discovered_handlers

def main():
    """Main entry point for the A2A server, supporting both HTTP and stdio modes."""
    parser = argparse.ArgumentParser(prog="a2a-server")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio JSON-RPC mode")
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP server")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP server")
    parser.add_argument("--log-level", choices=["debug","info","warning","error","critical"], default="info", help="Logging level")
    parser.add_argument("--log-file", help="Path to write logs to a file")
    parser.add_argument("--verbose-module", action="append", dest="verbose_modules", help="Module to log at DEBUG level")
    parser.add_argument("--quiet-module", action="append", dest="quiet_modules", help="Module:LEVEL pairs to set higher log levels")
    parser.add_argument("--no-discovery", action="store_true", help="Disable automatic handler discovery")
    parser.add_argument("--handler-package", action="append", dest="handler_packages", help="Packages to search for handlers")
    parser.add_argument("--list-handlers", action="store_true", help="List available handlers and exit")
    parser.add_argument("--config", "-c", help="Path to YAML configuration file (overrides other arguments)")
    args = parser.parse_args()

    # Implicit config: if no explicit --config and agent.yaml exists, use that
    config_explicit = bool(args.config)
    if not config_explicit and os.path.exists("agent.yaml"):
        args.config = "agent.yaml"

    # If using a YAML config
    if args.config:
        from a2a.server.run import load_config, setup_handlers
        config = load_config(args.config)

        # Apply CLI overrides only if config was explicit
        if config_explicit:
            if args.log_level:
                config["logging"]["level"] = args.log_level
            if args.log_file:
                config["logging"]["file"] = args.log_file
            if args.port:
                config["server"]["port"] = args.port
            if args.host:
                config["server"]["host"] = args.host

        # Merge quiet modules
        quiet = config["logging"].get("quiet_modules", {})
        if args.quiet_modules:
            for pair in args.quiet_modules:
                try:
                    mod, lvl = pair.split(":",1)
                    quiet[mod] = lvl
                except ValueError:
                    print(f"Invalid quiet module: {pair}, must be MODULE:LEVEL")
            config["logging"]["quiet_modules"] = quiet

        # Configure logging
        lc = config["logging"]
        configure_logging(level_name=lc["level"], file_path=lc.get("file"),
                          verbose_modules=lc.get("verbose_modules", []),
                          quiet_modules=lc.get("quiet_modules", {}))

        # List handlers and exit
        if args.list_handlers:
            from a2a.server.tasks.discovery import discover_all_handlers
            handlers = discover_all_handlers(args.handler_packages)
            print(f"Discovered {len(handlers)} handlers:")
            for cls in handlers:
                try:
                    inst = cls()
                    cts = ", ".join(inst.supported_content_types)
                    print(f"  - {inst.name}: {cls.__name__} ({cts})")
                except Exception as e:
                    print(f"  - {cls.__name__} [ERROR: {e}]")
            return

        # Setup handlers from config
        custom_handlers, default_handler = setup_handlers(config)
        use_discovery = config.get("handlers", {}).get("use_discovery", True) and not args.no_discovery
        handler_packages = args.handler_packages

        if args.stdio:
            # stdio mode
            event_bus = EventBus()
            manager = TaskManager(event_bus)
            protocol = JSONRPCProtocol()

            for h in custom_handlers:
                manager.register_handler(h, default=(h is default_handler))
            if use_discovery:
                register_discovered_handlers(manager, packages=handler_packages)
            register_methods(protocol, manager)

            logging.info("Starting A2A server in stdio mode")
            for line in sys.stdin:
                resp = handle_stdio_message(protocol, line)
                if resp:
                    print(resp, flush=True)
        else:
            # HTTP/WS/SSE mode
            # Pass handlers list or enable discovery
            handlers_list = custom_handlers if custom_handlers else None
            app = create_app(
                handlers=handlers_list,
                use_discovery=use_discovery,
                handler_packages=handler_packages
            )
            srv = config.get("server", {})
            host = srv.get("host", "127.0.0.1")
            port = srv.get("port", 8000)
            logging.info(f"Starting A2A HTTP server on {host}:{port}")
            uvicorn.run(app, host=host, port=port, log_level=lc["level"].lower())

    else:
        # No YAML config: CLI-only mode
        # Configure logging
        quiet = {}
        if args.quiet_modules:
            for pair in args.quiet_modules:
                try:
                    mod, lvl = pair.split(":",1)
                    quiet[mod] = lvl
                except ValueError:
                    print(f"Invalid quiet module: {pair}")
        configure_logging(level_name=args.log_level, file_path=args.log_file,
                          verbose_modules=args.verbose_modules, quiet_modules=quiet)

        # List handlers?
        if args.list_handlers:
            from a2a.server.tasks.discovery import discover_all_handlers
            handlers = discover_all_handlers(args.handler_packages)
            print(f"Discovered {len(handlers)} handlers:")
            for cls in handlers:
                try:
                    inst = cls()
                    cts = ", ".join(inst.supported_content_types)
                    print(f"  - {inst.name}: {cls.__name__} ({cts})")
                except Exception as e:
                    print(f"  - {cls.__name__} [ERROR: {e}]")
            return

        if args.stdio:
            event_bus = EventBus()
            manager = TaskManager(event_bus)
            protocol = JSONRPCProtocol()
            if not args.no_discovery:
                register_discovered_handlers(manager, packages=args.handler_packages)
            register_methods(protocol, manager)

            logging.info("Starting A2A server in stdio mode")
            for line in sys.stdin:
                resp = handle_stdio_message(protocol, line)
                if resp:
                    print(resp, flush=True)
        else:
            # HTTP/WS/SSE with discovery
            handlers_list = None
            app = create_app(
                handlers=handlers_list,
                use_discovery=not args.no_discovery,
                handler_packages=args.handler_packages
            )
            logging.info(f"Starting A2A HTTP server on {args.host}:{args.port}")
            uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()