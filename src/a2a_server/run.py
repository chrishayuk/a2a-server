#!/usr/bin/env python3
# a2a_server/run.py
"""
Simplified entry point for A2A server with YAML configuration support and agent cards.
"""
import logging

import uvicorn
from fastapi import FastAPI

from a2a_server.arguments import parse_args
from a2a_server.config import load_config
from a2a_server.handlers_setup import setup_handlers
from a2a_server.logging import configure_logging
from a2a_server.app import create_app


def run_server():
    # ── Parse CLI args ──────────────────────────────────────────────
    args = parse_args()

    # ── Load & override config ──────────────────────────────────────
    cfg = load_config(args.config)
    if args.log_level:
        cfg["logging"]["level"] = args.log_level
    if args.handler_packages:
        cfg["handlers"]["handler_packages"] = args.handler_packages
    if args.no_discovery:
        cfg["handlers"]["use_discovery"] = False

    # ── Logging ─────────────────────────────────────────────────────
    L = cfg["logging"]
    configure_logging(
        level_name=L["level"],
        file_path=L.get("file"),
        verbose_modules=L.get("verbose_modules", []),
        quiet_modules=L.get("quiet_modules", {}),
    )

    # ── Handlers setup ──────────────────────────────────────────────
    handlers_cfg = cfg["handlers"]
    all_handlers, default_handler = setup_handlers(handlers_cfg)
    use_discovery = handlers_cfg.get("use_discovery", True)

    # Promote default to front
    if default_handler:
        handlers_list = [default_handler] + [
            h for h in all_handlers if h is not default_handler
        ]
    else:
        handlers_list = all_handlers or None

    # ── Build FastAPI app ───────────────────────────────────────────
    app: FastAPI = create_app(
        handlers=handlers_list,
        use_discovery=use_discovery,
        handler_packages=handlers_cfg.get("handler_packages"),
        handlers_config=handlers_cfg,
        enable_flow_diagnosis=args.enable_flow_diagnosis,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # ── Optionally list all routes ──────────────────────────────────
    if args.list_routes:
        for route in app.routes:
            if hasattr(route, "path"):
                print(route.path)

    # ── Launch Uvicorn ──────────────────────────────────────────────
    host = cfg["server"].get("host", "127.0.0.1")
    port = cfg["server"].get("port", 8000)
    logging.info(f"Starting A2A server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level=L["level"])


if __name__ == "__main__":
    # run the server
    run_server()

