#!/usr/bin/env python3
# File: a2a/server/__main__.py
"""
CLI entrypoint for a2a-server: supports HTTP/WS/SSE or stdio mode,
optional YAML config, auto‑picks up agent.yaml if present.

Uses explicit route registration for direct handler mounting:
- /rpc, /ws, /events for the default handler
- /{name}/rpc, /{name}/ws, /{name}/events for specific handlers
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
from a2a.server.tasks.discovery import register_discovered_handlers, discover_all_handlers
from a2a.server.run import load_config, setup_handlers

def main():
    parser = argparse.ArgumentParser(prog="a2a-server")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio JSON-RPC mode")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    parser.add_argument("--log-level", choices=["debug","info","warning","error","critical"], default="info")
    parser.add_argument("--log-file", help="Log file path")
    parser.add_argument("--verbose-module", action="append", dest="verbose_modules")
    parser.add_argument("--quiet-module", action="append", dest="quiet_modules")
    parser.add_argument("--no-discovery", action="store_true", help="Disable automatic handler discovery")
    parser.add_argument("--handler-package", action="append", dest="handler_packages", help="Packages to search for handlers")
    parser.add_argument("--list-handlers", action="store_true", help="List available handlers and exit")
    parser.add_argument("--list-routes", action="store_true", help="List all registered routes after initialization")
    parser.add_argument("-c", "--config", help="YAML config path")
    args = parser.parse_args()

    # If no config specified but agent.yaml exists, use it
    if not args.config and os.path.exists("agent.yaml"):
        args.config = "agent.yaml"

    # Load and merge configuration
    cfg = load_config(args.config) if args.config else {}
    
    # Override with CLI args
    if args.log_level:
        cfg.setdefault("logging", {}).setdefault("level", args.log_level)
    if args.log_file:
        cfg.setdefault("logging", {}).setdefault("file", args.log_file)
    if args.host:
        cfg.setdefault("server", {}).setdefault("host", args.host)
    if args.port:
        cfg.setdefault("server", {}).setdefault("port", args.port)

    # Handle quiet modules
    quiet = cfg.get("logging", {}).get("quiet_modules", {})
    if args.quiet_modules:
        for m in args.quiet_modules:
            try:
                mod, lvl = m.split(":",1)
                quiet[mod] = lvl
            except ValueError:
                print(f"Ignoring invalid quiet-module '{m}'")
        cfg.setdefault("logging", {})["quiet_modules"] = quiet

    # Configure logging
    L = cfg.get("logging", {})
    configure_logging(
        level_name=L.get("level", args.log_level),
        file_path=L.get("file"),
        verbose_modules=L.get("verbose_modules", args.verbose_modules or []),
        quiet_modules=L.get("quiet_modules", {})
    )

    # Handle --list-handlers option
    if args.list_handlers:
        found = discover_all_handlers(args.handler_packages)
        print(f"Discovered {len(found)} handlers:")
        for cls in found:
            try:
                inst = cls()
                print(f"  - {inst.name}: {cls.__name__}")
            except Exception:
                print(f"  - {cls.__name__} [error instantiating]")
        return

    # Setup handlers from config
    handlers_config = cfg.get("handlers", {})
    custom_handlers, default_handler = setup_handlers(handlers_config)
    use_disc = handlers_config.get("use_discovery", True) and not args.no_discovery
    
    # Handle stdio mode
    if args.stdio:
        eb = EventBus()
        mgr = TaskManager(eb)
        proto = JSONRPCProtocol()

        # Register handlers
        for h in custom_handlers:
            mgr.register_handler(h, default=(h is default_handler))
            
        # Register discovered handlers if enabled
        if use_disc:
            register_discovered_handlers(mgr, packages=args.handler_packages)
            
        # Register RPC methods
        register_methods(proto, mgr)

        # Process stdio messages
        logging.info("Starting stdio mode")
        for line in sys.stdin:
            out = handle_stdio_message(proto, line)
            if out:
                print(out, flush=True)
        return

    # Create the FastAPI application
    app = create_app(
        handlers=custom_handlers if custom_handlers else None,
        use_discovery=use_disc,
        handler_packages=args.handler_packages
    )

    # Run the server
    host = cfg.get("server", {}).get("host", "127.0.0.1")
    port = cfg.get("server", {}).get("port", 8000)
    logging.info(f"Starting HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level=L.get("level", "info"))

if __name__ == "__main__":
    main()