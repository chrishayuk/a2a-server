#!/usr/bin/env python3
# a2a/server/run.py
"""
Simplified entry point for A2A server with YAML configuration support and agent cards.
"""
import argparse
import pkgutil
import importlib
import inspect
import yaml
import os
import logging
from typing import Optional, Dict, Any, Tuple, List, Type

import uvicorn
from fastapi import FastAPI

from a2a.server.logging import configure_logging
from a2a.server.app import create_app
from a2a.server.tasks.task_handler import TaskHandler
from a2a.server.tasks.discovery import discover_all_handlers

# Default configuration
DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
    },
    "logging": {
        "level": "info",
        "file": None,
        "verbose_modules": [],
        "quiet_modules": {
            "httpx": "ERROR",
            "LiteLLM": "ERROR",
            "google.adk": "ERROR",
            "uvicorn": "WARNING",
        }
    },
    "handlers": {
        "use_discovery": True,
        "handler_packages": [],
        "default": None,
    }
}

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from a YAML file with defaults."""
    cfg = DEFAULT_CONFIG.copy()
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            user_cfg = yaml.safe_load(f)
        if user_cfg:
            deep_update(cfg, user_cfg)
    return cfg

def deep_update(target: Dict, src: Dict) -> None:
    """Recursively merge src into target."""
    for k, v in src.items():
        if k in target and isinstance(target[k], dict) and isinstance(v, dict):
            deep_update(target[k], v)
        else:
            target[k] = v

def find_handler_class(handler_type: str) -> Optional[Type[TaskHandler]]:
    """Locate a TaskHandler subclass by import path or discovery."""
    # Fully‑qualified path?
    if "." in handler_type:
        try:
            mod_path, cls_name = handler_type.rsplit(".", 1)
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            if issubclass(cls, TaskHandler):
                return cls
            logging.error(f"{handler_type} is not a TaskHandler subclass")
        except Exception as e:
            logging.error(f"Error importing handler {handler_type}: {e}")
        return None

    # Try discovery list
    for cls in discover_all_handlers():
        if cls.__name__ == handler_type:
            return cls

    # Walk the handlers package for abstract classes
    pkg = "a2a.server.tasks.handlers"
    try:
        root = importlib.import_module(pkg)
        for _, name, _ in pkgutil.walk_packages(root.__path__, pkg + "."):
            try:
                m = importlib.import_module(name)
                for _, obj in inspect.getmembers(m, inspect.isclass):
                    if obj.__name__ == handler_type and issubclass(obj, TaskHandler):
                        return obj
            except ImportError:
                continue
    except ImportError:
        pass

    logging.error(f"Could not find handler class '{handler_type}'")
    return None

def load_object(spec: str) -> Any:
    """Dynamically import any referenced object."""
    if "." in spec:
        try:
            mod_path, attr = spec.rsplit(".", 1)
            mod = importlib.import_module(mod_path)
            return getattr(mod, attr)
        except Exception:
            pass

    # fallback common patterns
    for pat in (
        spec,
        f"{spec}.{spec}",
        f"{spec}_agent",
        f"{spec}_agent.{spec}",
        f"agents.{spec}",
        f"{spec}.agent"
    ):
        try:
            if "." in pat:
                mp, attr = pat.rsplit(".", 1)
                m = importlib.import_module(mp)
                if hasattr(m, attr):
                    return getattr(m, attr)
            else:
                m = importlib.import_module(pat)
                if hasattr(m, 'agent'):
                    return m.agent
        except ImportError:
            pass

    raise ImportError(f"Could not locate object '{spec}'")

def prepare_handler_params(
    handler_cls: Type[TaskHandler],
    cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build kwargs for handler_cls.__init__:
    - include only those keys that match the init signature (plus 'name')
    - attempt to load strings via import for other object params
    """
    sig = inspect.signature(handler_cls.__init__)
    valid_params = set(sig.parameters.keys()) - {"self"}
    params: Dict[str, Any] = {}

    for k, v in cfg.items():
        if k in ("type", "agent_card"):
            continue
        if k not in valid_params:
            # skip unknown args
            continue
        if k != "name" and isinstance(v, str):
            # try to import
            try:
                params[k] = load_object(v)
                logging.debug(f"Prepared param {k} → {params[k]}")
                continue
            except Exception:
                pass
        params[k] = v

    return params

def setup_handlers(
    handlers_cfg: Dict[str, Any]
) -> Tuple[List[TaskHandler], Optional[TaskHandler]]:
    """
    Instantiate everything under 'handlers' in the config.
    Returns (all_handlers, default_handler).
    """
    all_handlers: List[TaskHandler] = []
    default_inst: Optional[TaskHandler] = None
    default_key = handlers_cfg.get("default")

    for key, sub in handlers_cfg.items():
        if key in ("use_discovery", "handler_packages", "default"):
            continue
        if not isinstance(sub, dict):
            continue

        htype = sub.get("type")
        if not htype:
            logging.warning(f"Handler '{key}' missing 'type'")
            continue

        cls = find_handler_class(htype)
        if not cls:
            continue

        sub.setdefault("name", key)
        params = prepare_handler_params(cls, sub)

        try:
            inst = cls(**params)
            # attach the raw agent_card dict, if any
            if "agent_card" in sub:
                setattr(inst, "agent_card", sub["agent_card"])
                logging.debug(f"Attached agent_card to handler '{key}'")

            all_handlers.append(inst)
            if key == default_key:
                default_inst = inst

        except Exception as e:
            logging.error(f"Error instantiating handler '{key}': {e}", exc_info=True)

    return all_handlers, default_inst

def run_server():
    parser = argparse.ArgumentParser(description="A2A Server (YAML config)")
    parser.add_argument("-c", "--config", help="YAML config path")
    parser.add_argument(
        "-p", "--handler-package",
        action="append", dest="handler_packages",
        help="Additional packages to search for handlers"
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="Disable automatic handler discovery"
    )
    parser.add_argument(
        "--log-level",
        choices=["debug","info","warning","error","critical"],
        help="Override configured log level"
    )
    parser.add_argument(
        "--list-routes",
        action="store_true",
        help="List all registered routes after initialization"
    )
    args = parser.parse_args()

    # Load & merge YAML config
    cfg = load_config(args.config)
    if args.log_level:
        cfg["logging"]["level"] = args.log_level
    if args.handler_packages:
        cfg["handlers"]["handler_packages"] = args.handler_packages
    if args.no_discovery:
        cfg["handlers"]["use_discovery"] = False

    # Configure logging
    L = cfg["logging"]
    configure_logging(
        level_name=L["level"],
        file_path=L.get("file"),
        verbose_modules=L.get("verbose_modules", []),
        quiet_modules=L.get("quiet_modules", {})
    )

    # Instantiate handlers
    handlers_config = cfg["handlers"]
    custom_handlers, default_handler = setup_handlers(handlers_config)

    # ── Promote the YAML‑specified default to the front ───────────────
    if default_handler:
        handlers_list = [default_handler] + [
            h for h in custom_handlers if h is not default_handler
        ]
    else:
        handlers_list = custom_handlers or None

    # Create FastAPI app with handlers and their config
    app: FastAPI = create_app(
        handlers=handlers_list,
        use_discovery=handlers_config["use_discovery"],
        handler_packages=handlers_config["handler_packages"],
        handlers_config=handlers_config
    )

    # Run
    host = cfg["server"].get("host", "127.0.0.1")
    port = cfg["server"].get("port", 8000)
    logging.info(f"Starting A2A server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level=L["level"])

if __name__ == "__main__":
    run_server()