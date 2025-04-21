#!/usr/bin/env python3
# a2a/client/chat/commands/help.py
"""
Help commands for the A2A client interface.
Includes help and general utility commands.
"""
from typing import List, Dict, Any
from rich import print
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.console import Console

# Import the registration function
from a2a.client.chat.commands import register_command

# Help text for different sections
GENERAL_HELP = """
## A2A Client Commands

A2A Client provides several commands that map directly to A2A protocol methods:

- `/send <text>`: Send a task with the given text (tasks/send)
- `/get <id>`: Get task details by ID (tasks/get)
- `/cancel <id>`: Cancel a task (tasks/cancel)
- `/resubscribe <id>`: Subscribe to updates for an existing task (tasks/resubscribe)
- `/send_subscribe <text>`: Send a task and subscribe to its updates (tasks/sendSubscribe)

Use `/help <command>` for detailed help on any specific command.
"""

TASK_COMMANDS_HELP = """
## Task Commands

A2A Client provides commands that map directly to A2A protocol methods:

- `/send <text>`: Send a task with the given text (tasks/send)
  - Example: `/send Hello, please summarize this conversation`

- `/get <id>`: Get task details by ID (tasks/get)
  - Example: `/get 123e4567-e89b-12d3-a456-426614174000`

- `/cancel <id>`: Cancel a running task (tasks/cancel)
  - Example: `/cancel 123e4567-e89b-12d3-a456-426614174000`

- `/resubscribe <id>`: Subscribe to updates for an existing task (tasks/resubscribe)
  - Example: `/resubscribe 123e4567-e89b-12d3-a456-426614174000`
  - Alias: `/watch <id>` (backward compatibility)

- `/send_subscribe <text>`: Send a task and subscribe to its updates (tasks/sendSubscribe)
  - Example: `/send_subscribe Tell me a joke`
  - Aliases: `/sendsubscribe <text>`, `/watch_text <text>` (backward compatibility)
"""

CONNECTION_COMMANDS_HELP = """
## Connection Commands

A2A Client provides commands for managing connections:

- `/connect <url>`: Connect to a specific A2A server
  - Example: `/connect http://localhost:8000/pirate_agent`

- `/server`: Show current server connection information

- `/servers`: List all available preconfigured servers

- `/use <name>`: Switch to a different preconfigured server
  - Example: `/use chef_agent`
"""

DISPLAY_COMMANDS_HELP = """
## Display Commands

A2A Client provides commands for controlling the display:

- `/verbose` or `/v`: Toggle verbose mode (showing full JSON responses)

- `/clear`: Clear the screen

- `/history`: Show command history

- `/debug_info`: Show detailed connection and debugging information

- `/exit` or `/quit`: Exit the client
"""

PROTOCOL_INFO = """
## A2A Protocol Methods

The A2A client commands are designed to align with the A2A protocol's JSON-RPC methods:

| Command | Protocol Method | Description |
|---------|-----------------|-------------|
| `/send` | tasks/send | Send a new task to the agent |
| `/get` | tasks/get | Retrieve a task by ID |  
| `/cancel` | tasks/cancel | Cancel a running task |
| `/resubscribe` | tasks/resubscribe | Subscribe to updates for an existing task |
| `/send_subscribe` | tasks/sendSubscribe | Send a task and subscribe to its updates |

This consistent naming makes it easier to understand how the CLI maps to the underlying protocol.
"""

async def cmd_help(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display help information for all commands or a specific command.
    
    Usage: 
      /help           - Show all commands
      /help <command> - Show help for a specific command
      /help tasks     - Show help about task-related commands
      /help connection - Show help about connection commands
      /help protocol  - Show information about A2A protocol methods
    """
    console = Console()
    
    # Special case for task commands help
    if len(cmd_parts) > 1 and cmd_parts[1].lower() in ("task", "tasks"):
        print(Panel(Markdown(TASK_COMMANDS_HELP), style="cyan", title="Task Commands Help"))
        return True
        
    # Special case for connection commands help
    if len(cmd_parts) > 1 and cmd_parts[1].lower() in ("connection", "connect", "server"):
        print(Panel(Markdown(CONNECTION_COMMANDS_HELP), style="cyan", title="Connection Commands Help"))
        return True
        
    # Special case for display commands help
    if len(cmd_parts) > 1 and cmd_parts[1].lower() in ("display", "ui"):
        print(Panel(Markdown(DISPLAY_COMMANDS_HELP), style="cyan", title="Display Commands Help"))
        return True
        
    # Special case for protocol info
    if len(cmd_parts) > 1 and cmd_parts[1].lower() in ("protocol", "a2a"):
        print(Panel(Markdown(PROTOCOL_INFO), style="cyan", title="A2A Protocol Information"))
        return True

    # Help for a specific command
    if len(cmd_parts) > 1:
        specific_cmd = cmd_parts[1].lower()
        if not specific_cmd.startswith('/'):
            specific_cmd = '/' + specific_cmd
            
        # Use the command handlers from the module
        from a2a.client.chat.commands import _COMMAND_HANDLERS
        
        if specific_cmd in _COMMAND_HANDLERS:
            handler = _COMMAND_HANDLERS[specific_cmd]
            
            # Extract module name for the heading
            module_name = handler.__module__.split('.')[-1].capitalize()
            
            help_text = f"## {specific_cmd}\n\n"
            
            if handler.__doc__:
                help_text += handler.__doc__.strip()
            else:
                help_text += "No detailed help available for this command."
            
            # Check if this is an alias and show the main command
            aliases = {}
            for cmd, hdlr in _COMMAND_HANDLERS.items():
                if hdlr == handler and cmd != specific_cmd:
                    aliases.setdefault(handler, []).append(cmd)
            
            if handler in aliases and len(aliases[handler]) > 0:
                help_text += "\n\n### Aliases\n\n"
                help_text += ", ".join(aliases[handler])
            
            # Add completions info if available
            from a2a.client.chat.commands import _COMMAND_COMPLETIONS
            if specific_cmd in _COMMAND_COMPLETIONS:
                help_text += "\n\n### Completions\n\n"
                help_text += ", ".join(_COMMAND_COMPLETIONS[specific_cmd])
            
            print(Panel(Markdown(help_text), style="cyan", title=f"Help: {specific_cmd} ({module_name})"))
        else:
            print(f"[yellow]Command {specific_cmd} not found. Try /help for a list of all commands.[/yellow]")
        
        return True
    
    # General help - get all commands
    from a2a.client.chat.commands import _COMMAND_HANDLERS
    
    # Count total commands (excluding aliases for the count)
    unique_handlers = set(_COMMAND_HANDLERS.values())
    total_unique_commands = len(unique_handlers)
    
    # Create a table
    table = Table(title=f"{len(_COMMAND_HANDLERS)} Available Commands ({total_unique_commands} unique)")
    
    # Add columns
    table.add_column("Command", style="green")
    table.add_column("Description")
    
    # Sort all commands
    sorted_commands = sorted(_COMMAND_HANDLERS.items())
    
    # Add rows for each command
    for cmd, handler in sorted_commands:
        # Extract description from docstring
        desc = "No description"
        if handler.__doc__:
            # Get the first non-empty line from the docstring
            for line in handler.__doc__.strip().split('\n'):
                line = line.strip()
                if line:
                    desc = line
                    break
        
        # Truncate long descriptions
        if len(desc) > 75:
            desc = desc[:72] + "..."
            
        table.add_row(cmd, desc)
    
    # Print the table
    console.print(table)
    
    # Show help note
    console.print("\nType [green]/help <command>[/green] for more information about a specific command.")
    console.print("For task commands, type [green]/help tasks[/green].")
    console.print("For connection commands, type [green]/help connection[/green].")
    console.print("For display commands, type [green]/help display[/green].")
    console.print("For A2A protocol information, type [green]/help protocol[/green].")
    
    return True

async def display_quick_help(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display a quick reference of common commands.
    
    Usage: /quickhelp
    """
    console = Console()
    
    # Create a table for common commands
    table = Table(title="Quick Command Reference")
    
    # Add columns
    table.add_column("Command", style="green")
    table.add_column("Description")
    
    # Add rows for common commands
    table.add_row("/help", "Display detailed help")
    table.add_row("/send <text>", "Send a task with the given text")
    table.add_row("/get <id>", "Get task details by ID") 
    table.add_row("/resubscribe <id>", "Subscribe to updates for an existing task")
    table.add_row("/send_subscribe <text>", "Send a task and subscribe to its updates")
    table.add_row("/cancel <id>", "Cancel a running task")
    table.add_row("/connect <url>", "Connect to a specific server")
    table.add_row("/clear", "Clear the screen")
    table.add_row("exit, quit", "Exit chat mode")
    
    console.print(table)
    console.print("\nType [green]/help[/green] for complete command listing or [green]/help <command>[/green] for details.")
    
    return True

# Register all commands in this module
register_command("/help", cmd_help)
register_command("/quickhelp", display_quick_help)
register_command("/qh", display_quick_help)