#!/usr/bin/env python3
# a2a_server/run.py
"""
CLI entry point for the A2A server.

Reads YAML config, optional CLI flags, then launches Uvicorn with sensible
defaults for container / PaaS environments.
"""

from __future__ import annotations

import logging
import os

import uvicorn
from fastapi import FastAPI

from a2a_server.arguments import parse_args
from a2a_server.config import load_config
from a2a_server.handlers_setup import setup_handlers
from a2a_server.logging import configure_logging
from a2a_server.app import create_app


def run_server() -> None:
    # ── Parse CLI args ──────────────────────────────────────────────
    args = parse_args()

    # ── Load config & apply CLI overrides ───────────────────────────
    cfg = load_config(args.config)

    if args.log_level:
        cfg["logging"]["level"] = args.log_level
    if args.handler_packages:
        cfg["handlers"]["handler_packages"] = args.handler_packages
    if args.no_discovery:
        cfg["handlers"]["use_discovery"] = False

    # ── Logging setup ───────────────────────────────────────────────
    L = cfg["logging"]
    configure_logging(
        level_name=L["level"],
        file_path=L.get("file"),
        verbose_modules=L.get("verbose_modules", []),
        quiet_modules=L.get("quiet_modules", {}),
    )

    # ── Handlers ----------------------------------------------------
    handlers_cfg = cfg["handlers"]
    all_handlers, default_handler = setup_handlers(handlers_cfg)
    use_discovery = handlers_cfg.get("use_discovery", True)

    handlers_list = (
        [default_handler] + [h for h in all_handlers if h is not default_handler]
        if default_handler
        else all_handlers or None
    )

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

    if args.list_routes:
        for route in app.routes:
            if hasattr(route, "path"):
                print(route.path)

    # ── Launch Uvicorn ──────────────────────────────────────────────
    host = cfg["server"].get("host", "0.0.0.0")          # 0.0.0.0 for Fly
    # Fly injects the port it proxies to via $PORT
    port = int(os.getenv("PORT", cfg["server"].get("port", 8000)))

    logging.info("Starting A2A server on http://%s:%s", host, port)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=L["level"].lower(),
        proxy_headers=True,                              # ← honours X-Forwarded-*
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "*"),
    )


if __name__ == "__main__":
    run_server()
