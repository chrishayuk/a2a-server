#!/usr/bin/env python3
"""
Async-native CLI entry-point for the A2A server (“python -m a2a_server”).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Optional

import uvicorn
from fastapi import FastAPI

from a2a_server.arguments import parse_args
from a2a_server.config import load_config
from a2a_server.handlers_setup import setup_handlers
from a2a_server.logging import configure_logging
from a2a_server.app import create_app

__all__ = ["_build_app", "_serve", "run_server"]  # ← exported for tests


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────
def _build_app(cfg: dict, args) -> FastAPI:
    """Instantiate the FastAPI app with handlers resolved from *cfg*."""
    handlers_cfg = cfg["handlers"]

    # explicit list beats discovery
    all_handlers, default_handler = setup_handlers(handlers_cfg)
    use_discovery = handlers_cfg.get("use_discovery", True)

    handlers_list: Optional[list] = (
        [default_handler] + [h for h in all_handlers if h is not default_handler]
        if default_handler
        else all_handlers or None
    )

    return create_app(
        handlers=handlers_list,
        use_discovery=use_discovery,
        handler_packages=handlers_cfg.get("handler_packages"),
        handlers_config=handlers_cfg,
        enable_flow_diagnosis=args.enable_flow_diagnosis,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )


async def _serve(app: FastAPI, host: str, port: int, log_level: str) -> None:
    """Run *app* under **uvicorn.Server** and handle SIGINT/SIGTERM."""
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
        proxy_headers=True,  # honour X-Forwarded-*
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "*"),
    )
    server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _graceful_exit(*_: object) -> None:  # noqa: ANN001
        if not server.should_exit:
            server.should_exit = True
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _graceful_exit)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: _graceful_exit())

    logging.info("Starting A2A server on http://%s:%s", host, port)
    await server.serve()
    await stop.wait()  # ensure caller sees graceful shutdown


# ────────────────────────────────────────────────────────────────────────────
# Public CLI
# ────────────────────────────────────────────────────────────────────────────
def run_server() -> None:
    """Entry invoked by ``python -m a2a_server`` OR the ``a2a-server`` script."""
    args = parse_args()

    # Load & merge config -----------------------------------------------------
    cfg = load_config(args.config)
    if args.log_level:
        cfg["logging"]["level"] = args.log_level
    if args.handler_packages:
        cfg["handlers"]["handler_packages"] = args.handler_packages
    if args.no_discovery:
        cfg["handlers"]["use_discovery"] = False

    # Logging -----------------------------------------------------------------
    L = cfg["logging"]
    configure_logging(
        level_name=L["level"],
        file_path=L.get("file"),
        verbose_modules=L.get("verbose_modules", []),
        quiet_modules=L.get("quiet_modules", {}),
    )

    # Build ASGI app ----------------------------------------------------------
    app = _build_app(cfg, args)

    if args.list_routes:
        for route in app.routes:
            if hasattr(route, "path"):
                print(route.path)

    # Gather runtime options --------------------------------------------------
    host = cfg["server"].get("host", "0.0.0.0")
    port = int(os.getenv("PORT", cfg["server"].get("port", 8000)))
    log_level = L["level"]

    # Block until server exits ------------------------------------------------
    asyncio.run(_serve(app, host, port, log_level))


if __name__ == "__main__":  # pragma: no cover
    run_server()
