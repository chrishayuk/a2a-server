# File: a2a/server/arguments.py
import argparse
from typing import List, Optional

def parse_args() -> argparse.Namespace:
    """
    Parse command‑line arguments for the A2A server.
    """
    parser = argparse.ArgumentParser("A2A Server (YAML config)")
    parser.add_argument(
        "-c", "--config",
        help="YAML config path"
    )
    parser.add_argument(
        "-p", "--handler-package",
        action="append",
        dest="handler_packages",
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
    parser.add_argument(
        "--enable-flow-diagnosis",
        action="store_true",
        help="Enable detailed flow diagnosis and tracing"
    )
    return parser.parse_args()
