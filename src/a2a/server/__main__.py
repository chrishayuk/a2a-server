#!/usr/bin/env python3
# a2a/server/__main__.py
"""
CLI entrypoint for a2a-server: supports HTTP/WS/SSE or stdio mode,
optional YAML config, auto‑picks up agent.yaml if present.

Supports mounting each configured handler under its own URL prefix,
with the YAML `default` handler served at the root path `/` if specified,
and per-handler health checks at each prefix.
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
    parser.add_argument("-c", "--config", help="YAML config path")
    args = parser.parse_args()

    if not args.config and os.path.exists("agent.yaml"):
        args.config = "agent.yaml"

    cfg = load_config(args.config) if args.config else {}
    if args.log_level:
        cfg.setdefault("logging", {}).setdefault("level", args.log_level)
    if args.log_file:
        cfg.setdefault("logging", {}).setdefault("file", args.log_file)
    if args.host:
        cfg.setdefault("server", {}).setdefault("host", args.host)
    if args.port:
        cfg.setdefault("server", {}).setdefault("port", args.port)

    quiet = cfg.get("logging", {}).get("quiet_modules", {})
    if args.quiet_modules:
        for m in args.quiet_modules:
            try:
                mod, lvl = m.split(":",1)
                quiet[mod] = lvl
            except ValueError:
                print(f"Ignoring invalid quiet-module '{m}'")
        cfg.setdefault("logging", {})["quiet_modules"] = quiet

    L = cfg.get("logging", {})
    configure_logging(
        level_name=L.get("level", args.log_level),
        file_path=L.get("file"),
        verbose_modules=L.get("verbose_modules", args.verbose_modules or []),
        quiet_modules=L.get("quiet_modules", {})
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
                print(f"  - {cls.__name__} [error instantiating]")
        return

    handlers_config = cfg.get("handlers", {})
    custom_handlers, default_handler = setup_handlers(handlers_config)
    use_disc = handlers_config.get("use_discovery", True) and not args.no_discovery

    if args.stdio:
        eb = EventBus()
        mgr = TaskManager(eb)
        proto = JSONRPCProtocol()

        for h in custom_handlers:
            mgr.register_handler(h, default=False)
        if use_disc:
            register_discovered_handlers(mgr, packages=args.handler_packages)
        register_methods(proto, mgr)

        logging.info("Starting stdio mode")
        for line in sys.stdin:
            out = handle_stdio_message(proto, line)
            if out:
                print(out, flush=True)
        return

    root_app = FastAPI(title="A2A Multi-Agent Server")

    @root_app.get("/", include_in_schema=False)
    async def health_root():
        return {
            "default_handler": default_handler.name if default_handler else None,
            "handlers": [h.name for h in custom_handlers]
        }

    # Register each handler under /<name> with health and RPC/SSE
    for handler in custom_handlers:
        prefix = f"/{handler.name}"
        sub_app = create_app(
            handlers=[handler], use_discovery=False, handler_packages=None
        )
        # Health routes
        sub_app.add_api_route(
            path="",
            endpoint=lambda name=handler.name, path=prefix: {
                "handler": name,
                "rpc": path + "/rpc",
                "events": path + "/events",
            },
            methods=["GET"], include_in_schema=False
        )
        sub_app.add_api_route(
            path="/",
            endpoint=lambda name=handler.name, path=prefix: {
                "handler": name,
                "rpc": path + "/rpc",
                "events": path + "/events",
            },
            methods=["GET"], include_in_schema=False
        )
        root_app.mount(prefix, sub_app)
        logging.info(f"Mounted handler '{handler.name}' at '{prefix}'")

    if default_handler:
        default_app = create_app(
            handlers=[default_handler], use_discovery=False, handler_packages=None
        )
        default_app.add_api_route(
            path="",
            endpoint=lambda name=default_handler.name: {
                "handler": name,
                "rpc": "/rpc",
                "events": "/events",
            },
            methods=["GET"], include_in_schema=False
        )
        default_app.add_api_route(
            path="/",
            endpoint=lambda name=default_handler.name: {
                "handler": name,
                "rpc": "/rpc",
                "events": "/events",
            },
            methods=["GET"], include_in_schema=False
        )
        root_app.mount("/", default_app)
        logging.info(f"Mounted default handler '{default_handler.name}' at '/' ")

    host = cfg.get("server", {}).get("host", "127.0.0.1")
    port = cfg.get("server", {}).get("port", 8000)
    logging.info(f"Starting HTTP server on {host}:{port}")
    uvicorn.run(root_app, host=host, port=port, log_level=L.get("level", "info"))

if __name__ == "__main__":
    main()
