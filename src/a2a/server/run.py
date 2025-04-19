#!/usr/bin/env python3
# a2a/server/run.py
"""
Simplified entry point for A2A server with YAML configuration support.
"""
import argparse
import pkgutil
import sys
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
        "default": None,
    }
}

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from a YAML file with defaults."""
    config = DEFAULT_CONFIG.copy()
    
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            user_config = yaml.safe_load(f)
            if user_config:
                deep_update(config, user_config)
    
    return config

def deep_update(target: Dict, source: Dict) -> None:
    """Recursively update nested dictionaries."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            deep_update(target[key], value)
        else:
            target[key] = value

def find_handler_class(handler_type: str) -> Optional[Type[TaskHandler]]:
    """Find a handler class by name using discovery or direct import."""
    # Try direct import if it's a full path
    if "." in handler_type:
        try:
            module_path, class_name = handler_type.rsplit(".", 1)
            module = importlib.import_module(module_path)
            handler_class = getattr(module, class_name)
            if issubclass(handler_class, TaskHandler):
                return handler_class
            logging.error(f"{handler_type} is not a TaskHandler subclass")
            return None
        except (ImportError, AttributeError) as e:
            logging.error(f"Error importing {handler_type}: {e}")
            return None
    
    # For simple names, check both discoverable and abstract handlers
    # First try normal discovery
    from a2a.server.tasks.discovery import discover_all_handlers
    all_handlers = discover_all_handlers()
    
    for handler_class in all_handlers:
        if handler_class.__name__ == handler_type:
            return handler_class
    
    # If not found, look for abstract handlers
    # This is useful for handlers marked with abstract=True like GoogleADKHandler
    packages = ['a2a.server.tasks.handlers']
    for package in packages:
        try:
            package_module = importlib.import_module(package)
            for _, name, _ in pkgutil.walk_packages(package_module.__path__, package_module.__name__ + '.'):
                try:
                    module = importlib.import_module(name)
                    for attr_name, obj in inspect.getmembers(module, inspect.isclass):
                        if (obj.__name__ == handler_type and 
                            issubclass(obj, TaskHandler) and 
                            obj is not TaskHandler):
                            # Found the handler, even if it's abstract
                            return obj
                except (ImportError, AttributeError) as e:
                    logging.warning(f"Error inspecting module {name}: {e}")
        except ImportError:
            logging.warning(f"Could not import package {package}")
    
    logging.error(f"Could not find handler type: {handler_type}")
    return None

def load_object(object_spec: str) -> Any:
    """
    Load any Python object by module path or using common patterns.
    
    This is a generic loader that can be used for agents, adapters, or other objects.
    """
    try:
        # Try direct import first
        if "." in object_spec:
            module_path, attr_name = object_spec.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, attr_name)
        
        # Try common patterns
        patterns = [
            f"{object_spec}",                  # Direct module name
            f"{object_spec}.{object_spec}",    # module.attr with same name
            f"{object_spec}_agent",            # module_agent
            f"{object_spec}_agent.{object_spec}",  # module_agent.attr
            f"agents.{object_spec}",           # agents.module
            f"{object_spec}.agent"             # module.agent
        ]
        
        for pattern in patterns:
            try:
                if "." in pattern:
                    module_path, attr_name = pattern.rsplit(".", 1)
                    module = importlib.import_module(module_path)
                    if hasattr(module, attr_name):
                        return getattr(module, attr_name)
                else:
                    module = importlib.import_module(pattern)
                    # Look for 'agent' attribute or the first attribute that matches the module name
                    if hasattr(module, 'agent'):
                        return module.agent
                    # Try to find anything with matching name
                    for attr_name in dir(module):
                        if attr_name.lower() == object_spec.lower():
                            return getattr(module, attr_name)
            except ImportError:
                continue
                
        raise ImportError(f"Could not find object '{object_spec}'")
    except Exception as e:
        logging.error(f"Error loading object {object_spec}: {e}")
        return None

def prepare_handler_params(handler_class: Type[TaskHandler], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare parameters for handler instantiation based on config and class signature.
    """
    # Copy all config entries except the `type` field
    params = {k: v for k, v in config.items() if k != "type"}

    # Inspect the handler’s __init__ signature
    sig = inspect.signature(handler_class.__init__)
    param_names = list(sig.parameters.keys())[1:]  # skip 'self'

    for param_name in param_names:
        # Never try to import the `name` parameter—use it verbatim
        if param_name == "name":
            continue

        # If given as a string, attempt to load it as an object
        if param_name in params and isinstance(params[param_name], str):
            try:
                params[param_name] = load_object(params[param_name])
                logging.debug(f"Loaded object for parameter {param_name}: {params[param_name]}")
            except Exception:
                # Import failed? Just leave it as the original string
                pass

    return params


def setup_handlers(config: Dict) -> Tuple[List[TaskHandler], Optional[TaskHandler]]:
    """Set up handlers based on configuration."""
    handlers_config = config.get("handlers", {})
    use_discovery = handlers_config.get("use_discovery", True)
    default_handler_name = handlers_config.get("default")
    
    custom_handlers = []
    default_handler = None
    
    # Process handler definitions
    for name, handler_config in handlers_config.items():
        # Skip non-handler entries
        if name in ("use_discovery", "default") or not isinstance(handler_config, dict):
            continue
            
        handler_type = handler_config.get("type")
        if not handler_type:
            logging.warning(f"Handler '{name}' missing 'type' field")
            continue
        
        # Find handler class using discovery or direct import
        handler_class = find_handler_class(handler_type)
            
        if not handler_class:
            logging.error(f"Could not load handler type: {handler_type}")
            continue
            
        # Create handler instance
        try:
            # Set name from config key if not explicitly provided
            if "name" not in handler_config:
                handler_config["name"] = name
                
            # Prepare parameters
            params = prepare_handler_params(handler_class, handler_config)
            
            # Instantiate handler
            handler = handler_class(**params)
            custom_handlers.append(handler)
            
            # Check if this is the default handler
            if name == default_handler_name:
                default_handler = handler
                
        except Exception as e:
            logging.error(f"Error creating handler '{name}': {e}", exc_info=True)
    
    return custom_handlers, default_handler

def run_server():
    """Run the A2A server using YAML configuration."""
    parser = argparse.ArgumentParser(description="A2A Server with YAML configuration")
    parser.add_argument(
        "--config", "-c",
        help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Override logging level from config"
    )
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Override log level if specified
    if args.log_level:
        config["logging"]["level"] = args.log_level
    
    # Configure logging
    log_config = config["logging"]
    configure_logging(
        level_name=log_config["level"],
        file_path=log_config.get("file"),
        verbose_modules=log_config.get("verbose_modules", []),
        quiet_modules=log_config.get("quiet_modules", {})
    )
    
    # Set up handlers
    custom_handlers, default_handler = setup_handlers(config)
    
    # Create FastAPI app
    handlers_config = config.get("handlers", {})
    app = create_app(
        use_handler_discovery=handlers_config.get("use_discovery", True),
        custom_handlers=custom_handlers,
        default_handler=default_handler
    )
    
    # Start server
    server_config = config.get("server", {})
    host = server_config.get("host", "127.0.0.1")
    port = server_config.get("port", 8000)
    
    logging.info(f"Starting A2A server on http://{host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_config["level"].lower()
    )

if __name__ == "__main__":
    run_server()