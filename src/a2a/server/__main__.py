#!/usr/bin/env python3
# a2a/server/__main__.py
"""
Command-line entrypoint to launch the A2A server with HTTP, WS, and SSE transports.
Supports optional stdio mode for CLI-based agents, and a configurable log level.
"""
import sys
import argparse
import logging
from a2a.server.logging import configure_logging
import uvicorn
from fastapi import FastAPI

from a2a.server.app import create_app
from a2a.server.transport.stdio import handle_stdio_message
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.pubsub import EventBus
from a2a.server.tasks.task_manager import TaskManager
from a2a.server.methods import register_methods
from a2a.server.tasks.discovery import register_discovered_handlers


def main():
    """Main entry point for the A2A server, supporting both HTTP and stdio modes."""
    parser = argparse.ArgumentParser(prog="a2a-server")

    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run in stdio JSON-RPC mode (reads from stdin, writes to stdout)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP server"
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Logging level"
    )
    parser.add_argument(
        "--log-file",
        help="Path to write logs to a file"
    )
    parser.add_argument(
        "--verbose-module",
        action="append",
        dest="verbose_modules",
        help="Module to log at DEBUG level (can be specified multiple times)"
    )
    parser.add_argument(
        "--quiet-module",
        action="append",
        dest="quiet_modules",
        help="Module:LEVEL pairs to set higher log levels (e.g. httpx:WARNING)"
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="Disable automatic handler discovery"
    )
    parser.add_argument(
        "--handler-package",
        action="append",
        dest="handler_packages",
        help="Packages to search for handlers (can be specified multiple times)"
    )
    parser.add_argument(
        "--list-handlers",
        action="store_true",
        help="List available handlers and exit"
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to YAML configuration file (overrides other arguments)"
    )
    
    # parse
    args = parser.parse_args()

    # Handle YAML configuration if provided
    if args.config:
        from a2a.server.run import load_config, setup_handlers
        
        # Load YAML configuration
        config = load_config(args.config)
        
        # Override with command-line arguments if provided
        if args.log_level:
            config["logging"]["level"] = args.log_level
        if args.log_file:
            config["logging"]["file"] = args.log_file
        if args.port:
            config["server"]["port"] = args.port
        if args.host:
            config["server"]["host"] = args.host
        
        # Process quiet modules into a dictionary
        quiet_modules = config["logging"].get("quiet_modules", {})
        if args.quiet_modules:
            for pair in args.quiet_modules:
                try:
                    module, level = pair.split(':', 1)
                    quiet_modules[module] = level
                except ValueError:
                    print(f"Invalid quiet module format: {pair}. Use MODULE:LEVEL format.")
            config["logging"]["quiet_modules"] = quiet_modules
        
        # Configure logging
        log_config = config["logging"]
        configure_logging(
            level_name=log_config["level"],
            file_path=log_config.get("file"),
            verbose_modules=log_config.get("verbose_modules", []),
            quiet_modules=log_config.get("quiet_modules", {})
        )
        
        # Handle list-handlers mode
        if args.list_handlers:
            from a2a.server.tasks.discovery import discover_all_handlers
            
            handlers = discover_all_handlers(args.handler_packages)
            print(f"Discovered {len(handlers)} handlers:")
            for handler_class in handlers:
                try:
                    handler = handler_class()
                    content_types = ", ".join(handler.supported_content_types)
                    print(f"  - {handler.name}: {handler_class.__name__} ({content_types})")
                except Exception as e:
                    print(f"  - {handler_class.__name__} [ERROR: {e}]")
            return
        
        if args.stdio:
            # In stdio mode, we run our JSON-RPC loop on stdin/stdout
            event_bus = EventBus()
            manager = TaskManager(event_bus)
            protocol = JSONRPCProtocol()
            
            # Set up handlers from YAML configuration
            custom_handlers, default_handler = setup_handlers(config)
            
            # Register custom handlers if any
            if custom_handlers:
                for handler in custom_handlers:
                    is_default = default_handler is not None and handler is default_handler
                    manager.register_handler(handler, default=is_default)
            
            # Register handlers using discovery mechanism if enabled
            handlers_config = config.get("handlers", {})
            if handlers_config.get("use_discovery", True) and not args.no_discovery:
                register_discovered_handlers(manager, packages=args.handler_packages)
            
            register_methods(protocol, manager)

            logging.info("Starting A2A server in stdio mode")
            for line in sys.stdin:
                resp = handle_stdio_message(protocol, line)
                if resp:
                    print(resp, flush=True)
        else:
            # Create FastAPI app with handlers from YAML configuration
            custom_handlers, default_handler = setup_handlers(config)
            
            app = create_app(
                use_handler_discovery=config.get("handlers", {}).get("use_discovery", True) and not args.no_discovery,
                handler_packages=args.handler_packages,
                custom_handlers=custom_handlers,
                default_handler=default_handler
            )
            
            # Launch via Uvicorn
            server_config = config.get("server", {})
            host = server_config.get("host", "127.0.0.1")
            port = server_config.get("port", 8000)
            
            logging.info(f"Starting A2A HTTP server on {host}:{port}")
            uvicorn.run(
                app,
                host=host,
                port=port,
                log_level=log_config["level"].lower()
            )
    else:
        # Traditional command-line argument based approach
        
        # Process quiet modules into a dictionary
        quiet_modules = {}
        if args.quiet_modules:
            for pair in args.quiet_modules:
                try:
                    module, level = pair.split(':', 1)
                    quiet_modules[module] = level
                except ValueError:
                    print(f"Invalid quiet module format: {pair}. Use MODULE:LEVEL format.")

        # Configure logging with our custom function
        configure_logging(
            level_name=args.log_level,
            file_path=args.log_file,
            verbose_modules=args.verbose_modules,
            quiet_modules=quiet_modules
        )

        # Handle list-handlers mode
        if args.list_handlers:
            from a2a.server.tasks.discovery import discover_all_handlers
            
            handlers = discover_all_handlers(args.handler_packages)
            print(f"Discovered {len(handlers)} handlers:")
            for handler_class in handlers:
                try:
                    handler = handler_class()
                    content_types = ", ".join(handler.supported_content_types)
                    print(f"  - {handler.name}: {handler_class.__name__} ({content_types})")
                except Exception as e:
                    print(f"  - {handler_class.__name__} [ERROR: {e}]")
            return

        if args.stdio:
            # In stdio mode, we run our JSON-RPC loop on stdin/stdout
            event_bus = EventBus()
            manager = TaskManager(event_bus)
            protocol = JSONRPCProtocol()
            
            # Register handlers using discovery mechanism
            if not args.no_discovery:
                register_discovered_handlers(manager, packages=args.handler_packages)
            
            register_methods(protocol, manager)

            logging.info("Starting A2A server in stdio mode (log level=%s)", args.log_level)
            for line in sys.stdin:
                resp = handle_stdio_message(protocol, line)
                if resp:
                    print(resp, flush=True)
        else:
            # Launch FastAPI app via Uvicorn
            app: FastAPI = create_app(
                use_handler_discovery=not args.no_discovery,
                handler_packages=args.handler_packages
            )
            
            logging.info(
                "Starting A2A HTTP server on %s:%d (log level=%s)",
                args.host, args.port, args.log_level
            )
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                log_level=args.log_level.lower()
            )


if __name__ == "__main__":
    main()