# a2a/server/config.py
import yaml
import os
from typing import Dict, Any, List, Optional

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
            "google.adk": "ERROR"
        }
    },
    "handlers": {
        "use_discovery": True,
        "handler_packages": ["a2a.server.tasks.handlers"],
        "default_handler": "echo"
    }
}

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from a YAML file with defaults."""
    config = DEFAULT_CONFIG.copy()
    
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            user_config = yaml.safe_load(f)
            if user_config:
                # Deep merge the configs
                _deep_update(config, user_config)
    
    return config

def _deep_update(target, source):
    """Recursively update nested dictionaries."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_update(target[key], value)
        else:
            target[key] = value