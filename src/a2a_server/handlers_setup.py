# a2a_server/handlers_setup.py
import pkgutil
import importlib
import inspect
import logging
from typing import Any, Dict, Tuple, List, Optional, Type

from a2a_server.tasks.handlers.task_handler import TaskHandler
from a2a_server.tasks.discovery import discover_all_handlers

def find_handler_class(name: str) -> Optional[Type[TaskHandler]]:
    """Locate a TaskHandler subclass by import path or by discovery."""
    # fully-qualified import
    if "." in name:
        try:
            mod_path, cls_name = name.rsplit(".", 1)
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            if issubclass(cls, TaskHandler):
                return cls
        except Exception:
            logging.error("Couldn't import %s", name, exc_info=True)
        return None

    # auto-discovered by class name
    for cls in discover_all_handlers():
        if cls.__name__ == name:
            return cls

    # fallback: walk the handlers package
    pkg = importlib.import_module("a2a_server.tasks.handlers")
    for _, mod_name, _ in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        try:
            m = importlib.import_module(mod_name)
            for _, obj in inspect.getmembers(m, inspect.isclass):
                if obj.__name__ == name and issubclass(obj, TaskHandler):
                    return obj
        except ImportError:
            continue

    logging.error("Handler class not found: %s", name)
    return None


def load_object(spec: str) -> Any:
    """Try to import a dotted-path or common agent module patterns."""
    if "." in spec:
        mod, attr = spec.rsplit(".", 1)
        try:
            return getattr(importlib.import_module(mod), attr)
        except Exception:
            pass

    patterns = [
        spec,
        f"{spec}.{spec}",
        f"{spec}_agent",
        f"{spec}_agent.{spec}",
        f"agents.{spec}",
        f"{spec}.agent",
    ]
    for pat in patterns:
        try:
            if "." in pat:
                mp, at = pat.rsplit(".", 1)
                m = importlib.import_module(mp)
                if hasattr(m, at):
                    return getattr(m, at)
            else:
                m = importlib.import_module(pat)
                if hasattr(m, "agent"):
                    return m.agent
        except ImportError:
            pass

    raise ImportError(f"Could not locate object '{spec}'")


def prepare_params(cls: Type[TaskHandler], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Only keep __init__ params (plus name), importing strings when possible."""
    sig = inspect.signature(cls.__init__)
    valid = set(sig.parameters) - {"self"}
    params: Dict[str, Any] = {}
    for k, v in cfg.items():
        if k in ("type", "agent_card") or k not in valid:
            continue
        if k != "name" and isinstance(v, str):
            try:
                params[k] = load_object(v)
                logging.debug("Prepared param %s → %s", k, params[k])
                continue
            except Exception:
                pass
        params[k] = v
    return params


def setup_handlers(
    handlers_cfg: Dict[str, Any]
) -> Tuple[List[TaskHandler], Optional[TaskHandler]]:
    """
    Instantiate all handlers in config.
    Returns (all_handlers, default_handler).
    """
    all_handlers: List[TaskHandler] = []
    default_handler = None
    default_key = handlers_cfg.get("default_handler")

    for key, sub in handlers_cfg.items():
        if key in ("use_discovery", "handler_packages", "default_handler"):
            continue
        if not isinstance(sub, dict):
            continue
        htype = sub.get("type")
        if not htype:
            logging.warning("Handler %s missing type", key)
            continue

        cls = find_handler_class(htype)
        if not cls:
            continue

        sub.setdefault("name", key)
        params = prepare_params(cls, sub)
        try:
            inst = cls(**params)
            if "agent_card" in sub:
                setattr(inst, "agent_card", sub["agent_card"])
                logging.debug("Attached agent_card to %s", key)
            all_handlers.append(inst)
            if key == default_key:
                default_handler = inst
        except Exception as e:
            logging.error("Error instantiating %s: %s", key, e, exc_info=True)

    return all_handlers, default_handler
