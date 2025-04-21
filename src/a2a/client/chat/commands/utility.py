#!/usr/bin/env python3
# a2a/client/chat/commands/utility.py
"""
Utility commands for the A2A client interface.
Includes clear, verbose mode, and exit commands.
"""
import sys
from typing import List, Dict, Any

from rich import print
from rich.panel import Panel

# Import the registration function
from a2a.client.chat.commands import register_command

# Import UI helpers
from a2a.client.ui.ui_helpers import clear_screen

async def cmd_clear(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Clear the terminal screen.
    
    Usage: /clear
    """
    clear_screen()
    return True

async def cmd_verbose(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Toggle verbose mode for responses and tool calls.
    
    Usage: /verbose or /v
    """
    # Toggle verbose mode
    verbose_mode = context.get("verbose_mode", False)
    context["verbose_mode"] = not verbose_mode
    
    # Display the new mode
    if context["verbose_mode"]:
        print("[green]Verbose mode enabled. Full JSON responses will be shown.[/green]")
    else:
        print("[green]Verbose mode disabled. Compact responses will be shown.[/green]")
    
    return True

async def cmd_exit(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Exit the client.
    
    Usage: /exit or /quit
    """
    print(Panel("Exiting A2A client.", style="bold red"))
    
    # Set exit flag in context
    context["exit_requested"] = True
    
    return True

async def cmd_debug(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Toggle debug mode to show more detailed information.
    
    Usage: /debug
    """
    # Toggle debug mode
    debug_mode = context.get("debug_mode", False)
    context["debug_mode"] = not debug_mode
    
    # Configure logging
    import logging
    if context["debug_mode"]:
        logging.getLogger("a2a-client").setLevel(logging.DEBUG)
        print("[green]Debug mode enabled. Detailed logs will be shown.[/green]")
    else:
        logging.getLogger("a2a-client").setLevel(logging.INFO)
        print("[green]Debug mode disabled.[/green]")
    
    return True

async def cmd_history(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display command history.
    
    Usage: /history [n]
    
    Examples:
      /history    - Show all command history
      /history 5  - Show the last 5 commands
    """
    history = context.get("command_history", [])
    
    if not history:
        print("[yellow]No command history found.[/yellow]")
        return True
    
    # Determine how many entries to show
    limit = None
    if len(cmd_parts) > 1:
        try:
            limit = int(cmd_parts[1])
        except ValueError:
            print(f"[yellow]Invalid number: {cmd_parts[1]}. Showing all history.[/yellow]")
    
    # Show history
    if limit:
        display_history = history[-limit:]
        print(f"[cyan]Last {len(display_history)} commands:[/cyan]")
    else:
        display_history = history
        print(f"[cyan]Command history ({len(display_history)} commands):[/cyan]")
    
    for i, cmd in enumerate(display_history, 1):
        print(f"[dim]{i}.[/dim] {cmd}")
    
    return True

# Register all commands in this module
register_command("/clear", cmd_clear)
register_command("/verbose", cmd_verbose)
register_command("/v", cmd_verbose)
register_command("/exit", cmd_exit)
register_command("/quit", cmd_exit)
register_command("/debug", cmd_debug)
register_command("/history", cmd_history)