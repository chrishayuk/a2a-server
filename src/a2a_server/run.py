#!/usr/bin/env python3
from __future__ import annotations
"""Async-native CLI entry-point for the A2A server.

Changes (May-2025)
------------------
* Uvicorn handles signals; no manual SIGINT juggling.
* Awaitable `load_config` keeps startup async.
* Added log-level tweak to silence Uvicorn lifespan `CancelledError` tracebacks.
"""

import asyncio
import logging
import os
from typing import Optional

import uvicorn
from fastapi import FastAPI

from a2a_server.arguments import parse_args
from a2a_server.config import load_config
from a2a_server.handlers_setup import setup_handlers
from a2a_server.logging import configure_logging
from a2a_server.app import create_app

__all__ = ["_build_app", "_serve", "run_server"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app(cfg: dict, args) -> FastAPI:  # noqa: ANN001 - CLI helper
    """Instantiate a FastAPI app according to *cfg*."""
    handlers_cfg = cfg["handlers"]

    all_handlers, default = setup_handlers(handlers_cfg)
    use_discovery = handlers_cfg.get("use_discovery", True)

    handlers_list: Optional[list] = (
        [default] + [h for h in all_handlers if h is not default]
        if default
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
    """Run *app* via **uvicorn.Server** and exit silently on ^C."""
    cfg = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
        loop="asyncio",
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "*"),
    )
    server = uvicorn.Server(cfg)
    logging.info("Starting A2A server on http://%s:%s", host, port)

    try:
        await server.serve()
    except asyncio.CancelledError:
        pass  # clean Ctrl-C


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

async def _main_async() -> None:
    args = parse_args()

    # ── config ----------------------------------------------------------
    cfg = await load_config(args.config)
    if args.log_level:
        cfg["logging"]["level"] = args.log_level
    if args.handler_packages:
        cfg["handlers"]["handler_packages"] = args.handler_packages
    if args.no_discovery:
        cfg["handlers"]["use_discovery"] = False

    # ── logging ---------------------------------------------------------
    L = cfg["logging"]
    configure_logging(
        level_name=L["level"],
        file_path=L.get("file"),
        verbose_modules=L.get("verbose_modules", []),
        quiet_modules=L.get("quiet_modules", {}),
    )

    # suppress uvicorn lifespan CancelledError tracebacks
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

    # ── build ASGI app --------------------------------------------------
    app = _build_app(cfg, args)

    if args.list_routes:
        for r in app.routes:
            if hasattr(r, "path"):
                print(r.path)

    # ── runtime ---------------------------------------------------------
    host = cfg["server"].get("host", "0.0.0.0")
    port = int(os.getenv("PORT", cfg["server"].get("port", 8000)))
    log_level = L["level"]

    await _serve(app, host, port, log_level)


def run_server() -> None:
    """Entry-point for ``python -m a2a_server`` and the *a2a-server* script."""
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        pass  # silent Ctrl-C


if __name__ == "__main__":  # pragma: no cover
    run_server()
