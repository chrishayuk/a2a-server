#!/usr/bin/env python3
# a2a/server/__main__.py
"""
CLI entrypoint for a2a-server: supports HTTP/WS/SSE or stdio mode,
optional YAML config, auto‑picks up agent.yaml if present.
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
    parser.add_argument("-c", "--config", help="YAML config path")
    args = parser.parse_args()

    # Auto‑load agent.yaml if no explicit config
    if not args.config and os.path.exists("agent.yaml"):
        args.config = "agent.yaml"

    if args.config:
        # Delegate to run.py's logic
        from a2a.server.run import load_config, setup_handlers
        cfg = load_config(args.config)

        # If user explicitly passed --config, allow CLI flags to override YAML
        if parser.get_default("config") != args.config:
            if args.log_level: cfg["logging"]["level"] = args.log_level
            if args.log_file:  cfg["logging"]["file"]  = args.log_file
            if args.host:      cfg["server"]["host"]   = args.host
            if args.port:      cfg["server"]["port"]   = args.port

        # Merge quiet-modules
        quiet = cfg["logging"].get("quiet_modules", {})
        if args.quiet_modules:
            for m in args.quiet_modules:
                try:
                    mod, lvl = m.split(":",1)
                    quiet[mod] = lvl
                except ValueError:
                    print(f"Ignoring invalid quiet-module '{m}'")
            cfg["logging"]["quiet_modules"] = quiet

        # Configure logging
        L = cfg["logging"]
        configure_logging(
            level_name=L["level"],
            file_path=L.get("file"),
            verbose_modules=L.get("verbose_modules", []),
            quiet_modules=L.get("quiet_modules", {})
        )

        # List handlers and exit if requested
        if args.list_handlers:
            handlers = register_discovered_handlers  # to force import
            from a2a.server.tasks.discovery import discover_all_handlers
            found = discover_all_handlers(args.handler_packages)
            print(f"Discovered {len(found)} handlers:")
            for cls in found:
                try:
                    inst = cls()
                    print(f"  - {inst.name}: {cls.__name__}")
                except Exception:
                    print(f"  - {cls.__name__} [error instantiating]")
            return

        # Build custom handlers from YAML
        custom, _ = setup_handlers(cfg["handlers"])
        use_disc = cfg["handlers"].get("use_discovery", True) and not args.no_discovery

        if args.stdio:
            # stdio JSON-RPC mode
            eb = EventBus()
            mgr = TaskManager(eb)
            proto = JSONRPCProtocol()

            for h in custom:
                mgr.register_handler(h, default=False)
            if use_disc:
                register_discovered_handlers(mgr, packages=args.handler_packages)
            register_methods(proto, mgr)

            logging.info("Starting stdio mode")
            for line in sys.stdin:
                out = handle_stdio_message(proto, line)
                if out:
                    print(out, flush=True)

        else:
            # HTTP / WS / SSE mode
            app = create_app(
                handlers=custom or None,
                use_discovery=use_disc,
                handler_packages=args.handler_packages
            )
            h, p = cfg["server"]["host"], cfg["server"]["port"]
            logging.info(f"Starting HTTP server on {h}:{p}")
            uvicorn.run(app, host=h, port=p, log_level=L["level"])

    else:
        # No YAML config: purely CLI‑driven
        quiet = {}
        if args.quiet_modules:
            for m in args.quiet_modules:
                try:
                    mod, lvl = m.split(":",1)
                    quiet[mod] = lvl
                except ValueError:
                    pass

        configure_logging(
            level_name=args.log_level,
            file_path=args.log_file,
            verbose_modules=args.verbose_modules or [],
            quiet_modules=quiet
        )

        if args.list_handlers:
            from a2a.server.tasks.discovery import discover_all_handlers
            found = discover_all_handlers(args.handler_packages)
            print(f"Discovered {len(found)} handlers:")
            for cls in found:
                try:
                    inst = cls()
                    print(f"  - {inst.name}: {cls.__name__}")
                except Exception:
                    print(f"  - {cls.__name__} [error]")
            return

        if args.stdio:
            eb = EventBus()
            mgr = TaskManager(eb)
            proto = JSONRPCProtocol()
            if not args.no_discovery:
                register_discovered_handlers(mgr, packages=args.handler_packages)
            register_methods(proto, mgr)

            logging.info("Starting stdio mode")
            for line in sys.stdin:
                out = handle_stdio_message(proto, line)
                if out:
                    print(out, flush=True)

        else:
            app = create_app(
                handlers=None,
                use_discovery=not args.no_discovery,
                handler_packages=args.handler_packages
            )
            logging.info(f"Starting HTTP server on {args.host}:{args.port}")
            uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)

if __name__ == "__main__":
    main()