#!/usr/bin/env python3
# a2a_server/run.py
from __future__ import annotations
"""Async-native CLI entry-point for the A2A server."""
import logging
import os

# Set up quiet logging IMMEDIATELY before any other imports
logging.getLogger('chuk_sessions.session_manager').setLevel(logging.WARNING)
logging.getLogger('chuk_ai_session_manager.session_storage').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.ERROR)
logging.getLogger('google_adk.google.adk.models.registry').setLevel(logging.ERROR)

import asyncio
import uvicorn
from fastapi import FastAPI

from a2a_server.arguments import parse_args
from a2a_server.config import load_config
from a2a_server.logging import configure_logging

__all__ = ["_build_app", "_serve", "run_server"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app(cfg: dict, args) -> FastAPI:  # noqa: ANN001 - CLI helper
    """Instantiate a FastAPI app according to *cfg*."""
    from a2a_server.app import create_app
    
    handlers_cfg = cfg["handlers"]
    use_discovery = handlers_cfg.get("use_discovery", False)

    # Extract handler configurations for clean logging
    handler_configs = {
        k: v for k, v in handlers_cfg.items() 
        if k not in ['use_discovery', 'default_handler', 'handler_packages'] and isinstance(v, dict)
    }
    
    logger = logging.getLogger(__name__)
    logger.info(f"Configuring A2A server with {len(handler_configs)} handlers")
    if use_discovery:
        logger.info(f"Package discovery enabled for: {handlers_cfg.get('handler_packages', [])}")
    
    # Let app.py handle all handler registration
    return create_app(
        handlers=None,
        use_discovery=use_discovery,
        handler_packages=handlers_cfg.get("handler_packages"),
        handlers_config=handlers_cfg,
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
        # Disable features that might cause Content-Length issues
        proxy_headers=False,  # Disable proxy header processing
        access_log=False,     # Disable access logging
        server_header=False,  # Disable server header
        date_header=False,    # Disable date header
        # Use h11 with minimal configuration
        http="h11",
    )
    server = uvicorn.Server(cfg)
    logging.info("Starting A2A server on http://%s:%s (minimal config)", host, port)

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

    # ── Apply comprehensive logging configuration ──────────────────────
    L = cfg.get("logging", {})
    configure_logging(
        level_name=L.get("level", "info"),
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
    host = cfg.get("server", {}).get("host", "0.0.0.0")
    port = int(os.getenv("PORT", cfg.get("server", {}).get("port", 8000)))
    log_level = L.get("level", "info")

    await _serve(app, host, port, log_level)


def run_server() -> None:
    """Entry-point for ``python -m a2a_server`` and the *a2a-server* script."""
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        pass  # silent Ctrl-C


if __name__ == "__main__":  # pragma: no cover
    run_server()