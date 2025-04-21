#!/usr/bin/env python3
# a2a/client/chat/commands/connection.py
"""
Connection management commands for the A2A client interface.
Includes connect, server info, and server switching commands.
"""
import json
import os
import logging
from typing import List, Dict, Any, Tuple

from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.markdown import Markdown

# Import the registration function
from a2a.client.chat.commands import register_command

# Import the A2A client
from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.spec import TaskQueryParams

logger = logging.getLogger("a2a-client")


async def fetch_agent_card(base_url: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Fetch the agent card from the server.

    Args:
        base_url: The base URL of the server

    Returns:
        Tuple of (success, card_data)
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            url = f"{base_url}/agent-card.json"
            logger.debug(f"Fetching agent card from {url}")

            response = await client.get(url, timeout=3.0)
            if response.status_code == 200:
                data = response.json()
                return True, data
            else:
                logger.debug(f"Agent card not available: {response.status_code}")
                return False, {}
    except Exception as e:
        logger.debug(f"Error fetching agent card: {e}", exc_info=True)
        return False, {}


async def check_server_connection(base_url: str, client: A2AClient) -> bool:
    """
    Check if the server is responding to A2A protocol methods.

    Args:
        base_url: The base URL of the server
        client: The A2A client to use

    Returns:
        True if the server is responding, False otherwise
    """
    try:
        # Try to get a non-existent task
        params = TaskQueryParams(id="connection-test-000")
        await client.get_task(params)
        return True
    except JSONRPCError as e:
        # Expected: The task doesn't exist
        if "not found" in str(e).lower() or "tasknotfound" in str(e).lower():
            return True
        # Other errors may indicate partial support
        logger.warning(f"Unexpected error from server: {e}")
        return True
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return False


async def cmd_connect(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Connect to an A2A server by URL or server name.

    Usage: 
      /connect <url>         - Connect to a specific URL
      /connect <server_name> - Connect to a named server from config
    """
    quiet = context.get("quiet", False)

    if len(cmd_parts) < 2:
        print("[yellow]Error: No URL or server name provided. Usage: /connect <url or name>[/yellow]")
        return True

    # Resolve incoming target
    target = cmd_parts[1]
    server_names = context.get("server_names", {})
    if target in server_names:
        base_url = server_names[target]
        if not quiet:
            print(f"[dim]Using server '{target}' at {base_url}[/dim]")
    else:
        base_url = target
        if not base_url.startswith(("http://", "https://")):
            base_url = f"http://localhost:8000/{base_url.strip('/')}"
        if not quiet:
            print(f"[dim]Using direct URL: {base_url}[/dim]")

    # 1) Fetch the agent‑card if it exists
    if not quiet:
        print(f"[dim]Checking for agent card at {base_url}/agent-card.json...[/dim]")
    success, agent_data = await fetch_agent_card(base_url)

    if success:
        agent_name = agent_data.get("name", "Unknown Agent")
        print(f"[green]Found agent: {agent_name}[/green]")

        # 2) If the card itself has a "url", use that as the new base
        if agent_data.get("url"):
            base_url = agent_data["url"].rstrip("/")
            if not quiet:
                print(f"[dim]Re‑based via agent‑card 'url': {base_url}[/dim]")
        else:
            # 3) Otherwise apply any advertised mount/basePath
            mount = agent_data.get("mount") or agent_data.get("basePath", "").lstrip("/")
            if mount:
                base_url = base_url.rstrip("/") + "/" + mount
                if not quiet:
                    print(f"[dim]Applying mount point: /{mount} → new base_url: {base_url}[/dim]")

        context["agent_info"] = agent_data
    else:
        if not quiet:
            print(f"[dim]No agent card found, continuing with connection...[/dim]")

    # 4) Now build the proper endpoints
    rpc_url = base_url.rstrip("/") + "/rpc"
    events_url = base_url.rstrip("/") + "/events"

    try:
        if not quiet:
            print(f"[dim]Creating HTTP client for {rpc_url}...[/dim]")
        client = A2AClient.over_http(rpc_url)

        if not quiet:
            print(f"[dim]Testing connection to A2A server...[/dim]")
        if await check_server_connection(base_url, client):
            if not quiet:
                print(f"[green]Successfully connected to A2A server at {base_url}[/green]")
            context["client"] = client

            # Initialize SSE client on the correct /events path
            if not quiet:
                print(f"[dim]Creating SSE client for {events_url}...[/dim]")
            try:
                sse_client = A2AClient.over_sse(rpc_url, events_url)
                context["streaming_client"] = sse_client
                if not quiet:
                    print(f"[green]SSE client initialized[/green]")
            except Exception as e:
                if not quiet:
                    print(f"[yellow]Warning: Could not initialize SSE client: {e}[/yellow]")
                    print(f"[yellow]Some streaming functionality may not be available[/yellow]")

            # Finally, render the agent‑card UI if we have one
            if "agent_info" in context:
                try:
                    from a2a.client.chat.commands.agent import cmd_agent_card
                    await cmd_agent_card(["/agent_card"], context)
                except Exception as e:
                    if context.get("debug_mode"):
                        print(f"[yellow]Error displaying agent card: {e}[/yellow]")
                    # fallback: simple panel
                    info = context["agent_info"]
                    desc = info.get("description", "")
                    if desc:
                        console = Console()
                        console.print(Panel(desc, title=f"Connected to {info.get('name')}", border_style="green"))

            return True
        else:
            print(f"[red]Failed to connect to A2A server at {base_url}[/red]")
            print(f"[yellow]Make sure the server supports the A2A protocol[/yellow]")
            return True

    except Exception as e:
        print(f"[red]Error connecting to server: {e}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
        return True


async def cmd_disconnect(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Disconnect from the current A2A server.

    Usage: /disconnect
    """
    if "client" not in context and "streaming_client" not in context:
        print("[yellow]Not connected to any server.[/yellow]")
        return True

    base_url = context.get("base_url", "Unknown")

    # Clean up clients
    if "client" in context:
        client = context["client"]
        if hasattr(client, "transport") and hasattr(client.transport, "close"):
            try:
                await client.transport.close()
                print(f"[green]HTTP client disconnected[/green]")
            except Exception as e:
                print(f"[yellow]Error closing HTTP client: {e}[/yellow]")
        context.pop("client", None)

    if "streaming_client" in context:
        streaming_client = context["streaming_client"]
        if hasattr(streaming_client, "transport") and hasattr(streaming_client.transport, "close"):
            try:
                await streaming_client.transport.close()
                print(f"[green]SSE client disconnected[/green]")
            except Exception as e:
                print(f"[yellow]Error closing SSE client: {e}[/yellow]")
        context.pop("streaming_client", None)

    print(f"[green]Disconnected from {base_url}[/green]")
    return True


async def cmd_server(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display current server connection information.

    Usage: /server
    """
    console = Console()

    # Check if connected
    base_url = context.get("base_url")
    if not base_url:
        print("[yellow]Not connected to any server. Use /connect to connect.[/yellow]")
        return True

    # Find server name if available
    server_name = "Custom URL"
    server_names = context.get("server_names", {})
    for name, url in server_names.items():
        if url.rstrip("/") == base_url.rstrip("/"):
            server_name = name
            break

    # Get agent info if available
    agent_info = context.get("agent_info", {})
    agent_name = agent_info.get("name", "Unknown")
    agent_version = agent_info.get("version", "Unknown")

    # Create table for server info
    table = Table(title="Server Connection")
    table.add_column("Property", style="green")
    table.add_column("Value")

    table.add_row("Server Name", server_name)
    table.add_row("Base URL", base_url)
    table.add_row("RPC Endpoint", base_url.rstrip("/") + "/rpc")
    table.add_row("Events Endpoint", base_url.rstrip("/") + "/events")

    # Add agent info if available
    if agent_info:
        table.add_row("Agent Name", agent_name)
        table.add_row("Agent Version", agent_version)

    # Check if client is connected
    client_status = "[green]Connected[/green]" if context.get("client") else "[red]Disconnected[/red]"
    table.add_row("Client Status", client_status)

    # Check if streaming client is connected
    streaming_status = "[green]Available[/green]" if context.get("streaming_client") else "[yellow]Not initialized[/yellow]"
    table.add_row("Streaming Status", streaming_status)

    console.print(table)

    # Show capabilities if available
    if agent_info and "capabilities" in agent_info:
        caps = agent_info["capabilities"]
        if caps:
            caps_table = Table(title="Agent Capabilities")
            caps_table.add_column("Capability", style="cyan")
            for cap in caps:
                caps_table.add_row(cap)
            console.print(caps_table)

    return True


async def cmd_servers(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    List all available preconfigured servers.

    Usage: /servers
    """
    console = Console()

    # Get server names from context
    server_names = context.get("server_names", {})

    if not server_names:
        print("[yellow]No preconfigured servers found. You can still connect with /connect <url>[/yellow]")
        print("[dim]Use /load_config to load server configurations from a file.[/dim]")
        return True

    # Create table for server list
    table = Table(title="Available Servers")
    table.add_column("#", style="dim")
    table.add_column("Name", style="green")
    table.add_column("URL")

    # Add rows for each server
    for i, (name, url) in enumerate(server_names.items(), 1):
        current_marker = " [yellow]✓[/yellow]" if url.rstrip("/") == context.get("base_url", "").rstrip("/") else ""
        table.add_row(str(i), f"{name}{current_marker}", url)

    console.print(table)
    console.print("\nConnect to a server with [green]/connect <name>[/green] or [green]/use <#>[/green]")

    return True


async def cmd_use(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Switch to a different preconfigured server.

    Usage: /use <server_name or #>
    """
    if len(cmd_parts) < 2:
        print("[yellow]Error: No server name or number provided. Usage: /use <server_name or #>[/yellow]")
        return True

    target = cmd_parts[1]
    server_names = context.get("server_names", {})

    if target in server_names:
        await cmd_disconnect(["/disconnect"], context)
        return await cmd_connect(["/connect", target], context)

    try:
        idx = int(target) - 1
        if 0 <= idx < len(server_names):
            await cmd_disconnect(["/disconnect"], context)
            name = list(server_names.keys())[idx]
            return await cmd_connect(["/connect", name], context)
    except ValueError:
        pass

    print(f"[yellow]Server '{target}' not found. Use /servers to see available servers.[/yellow]")
    return True


async def cmd_load_config(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Load server configuration from a file.

    Usage: /load_config <file_path>
    """
    if len(cmd_parts) > 1:
        file_path = os.path.expanduser(cmd_parts[1])
    else:
        default_paths = [
            "~/.a2a/config.json",
            "~/.a2a/servers.json",
            "./a2a-config.json",
            "./servers.json"
        ]
        for path in default_paths:
            expanded = os.path.expanduser(path)
            if os.path.exists(expanded):
                file_path = expanded
                print(f"[dim]Using config file: {file_path}[/dim]")
                break
        else:
            print("[yellow]No config file specified and no default config found.[/yellow]")
            print("[yellow]Usage: /load_config <file_path>[/yellow]")
            return True

    try:
        with open(file_path, 'r') as f:
            config = json.load(f)
        servers = config.get("servers", {})
        if not servers:
            print(f"[yellow]No servers found in config file: {file_path}[/yellow]")
            return True
        context["server_names"] = servers
        context["config_file"] = file_path
        print(f"[green]Loaded {len(servers)} servers from {file_path}[/green]")
        await cmd_servers(cmd_parts, context)
        return True
    except FileNotFoundError:
        print(f"[red]Config file not found: {file_path}[/red]")
        return True
    except json.JSONDecodeError:
        print(f"[red]Invalid JSON in config file: {file_path}[/red]")
        return True
    except Exception as e:
        print(f"[red]Error loading config: {e}[/red]")
        if context.get("debug_mode", False):
            traceback.print_exc()
        return True


async def cmd_save_config(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Save current server configuration to a file.

    Usage: /save_config [file_path]
    """
    if len(cmd_parts) > 1:
        file_path = os.path.expanduser(cmd_parts[1])
    elif context.get("config_file"):
        file_path = context["config_file"]
    else:
        file_path = os.path.expanduser("~/.a2a/config.json")

    servers = context.get("server_names", {})
    if not servers:
        print("[yellow]No servers configured to save.[/yellow]")
        return True

    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        print(f"[dim]Created directory: {directory}[/dim]")

    try:
        with open(file_path, 'w') as f:
            json.dump({"servers": servers}, f, indent=2)
        context["config_file"] = file_path
        print(f"[green]Saved {len(servers)} servers to {file_path}[/green]")
        return True
    except Exception as e:
        print(f"[red]Error saving config: {e}[/red]")
        if context.get("debug_mode", False):
            traceback.print_exc()
        return True


async def cmd_add_server(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Add a server to the configuration.

    Usage: /add_server <name> <url>
    """
    if len(cmd_parts) < 3:
        print("[yellow]Error: Missing arguments. Usage: /add_server <name> <url>[/yellow]")
        return True

    name, url = cmd_parts[1], cmd_parts[2]
    if not url.startswith(("http://", "https://")):
        url = f"http://localhost:8000/{url.strip('/')}"
        print(f"[dim]Normalized URL to: {url}[/dim]")

    servers = context.get("server_names", {})
    servers[name] = url
    context["server_names"] = servers
    print(f"[green]Added server '{name}' at {url}[/green]")
    await cmd_servers(cmd_parts, context)
    return True


async def cmd_remove_server(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Remove a server from the configuration.

    Usage: /remove_server <name>
    """
    if len(cmd_parts) < 2:
        print("[yellow]Error: No server name provided. Usage: /remove_server <name>[/yellow]")
        return True

    name = cmd_parts[1]
    servers = context.get("server_names", {})
    if name not in servers:
        print(f"[yellow]Server '{name}' not found.[/yellow]")
        return True

    url = servers.pop(name)
    context["server_names"] = servers
    print(f"[green]Removed server '{name}' at {url}[/green]")
    await cmd_servers(cmd_parts, context)
    return True


# Register all commands in this module
register_command("/connect", cmd_connect)
register_command("/disconnect", cmd_disconnect)
register_command("/server", cmd_server)
register_command("/servers", cmd_servers)
register_command("/use", cmd_use)
register_command("/load_config", cmd_load_config)
register_command("/save_config", cmd_save_config)
register_command("/add_server", cmd_add_server)
register_command("/remove_server", cmd_remove_server)
