#!/usr/bin/env python3
# a2a/client/chat/commands/__init__.py
"""
Command system for the A2A Client chat interface.

This module provides a registry for chat commands and utility functions
for command handling and completion.
"""
from typing import Dict, List, Any, Callable, Awaitable, Set, Optional, Tuple
import logging
import inspect
import importlib
import pkgutil
import sys
from pathlib import Path

# Type for command handlers
CommandHandler = Callable[[List[str], Dict[str, Any]], Awaitable[bool]]

# Registry of command handlers
_COMMAND_HANDLERS: Dict[str, CommandHandler] = {}

# Registry of command completions
_COMMAND_COMPLETIONS: Dict[str, List[str]] = {}

logger = logging.getLogger("a2a-client")

def register_command(cmd: str, handler: CommandHandler, completions: Optional[List[str]] = None) -> None:
    """
    Register a command handler.
    
    Args:
        cmd: The command string (starting with /)
        handler: The async function that handles the command
        completions: Optional list of completion strings for this command
    """
    _COMMAND_HANDLERS[cmd] = handler
    if completions:
        _COMMAND_COMPLETIONS[cmd] = completions

def get_command_completions(text: str) -> List[str]:
    """
    Get command completions for the given text.
    
    Args:
        text: The text to complete
        
    Returns:
        A list of possible completions
    """
    # First word completions (command names)
    if " " not in text:
        return [cmd for cmd in _COMMAND_HANDLERS.keys() if cmd.startswith(text)]
    
    # Argument completions
    cmd_parts = text.split()
    main_cmd = cmd_parts[0]
    
    if main_cmd in _COMMAND_COMPLETIONS:
        # For commands with registered completions, return matching ones
        completions = _COMMAND_COMPLETIONS[main_cmd]
        current_word = cmd_parts[-1] if len(cmd_parts) > 1 else ""
        return [f"{main_cmd} {comp}" for comp in completions if comp.startswith(current_word)]
    
    return []

async def handle_command(command: str, context: Dict[str, Any]) -> bool:
    """
    Handle a command string.
    
    Args:
        command: The command string (starting with /)
        context: The current command context
        
    Returns:
        True if the command was handled, False otherwise
    """
    cmd_parts = command.split()
    if not cmd_parts:
        return False
        
    cmd = cmd_parts[0].lower()
    
    if cmd in _COMMAND_HANDLERS:
        try:
            return await _COMMAND_HANDLERS[cmd](cmd_parts, context)
        except Exception as e:
            logger.error(f"Error handling command {cmd}: {e}")
            from rich import print
            print(f"[red]Error handling command {cmd}: {e}[/red]")
            return True
    
    from rich import print
    print(f"[yellow]Unknown command: {cmd}. Type /help for available commands.[/yellow]")
    return True

def _discover_and_load_commands() -> None:
    """
    Discover and load all command modules.
    """
    commands_path = Path(__file__).parent
    
    if not commands_path.is_dir():
        logger.error(f"Commands directory not found: {commands_path}")
        return
        
    logger.debug(f"Discovering commands in {commands_path}")
    
    # Get all Python files in the commands directory
    for _, name, is_pkg in pkgutil.iter_modules([str(commands_path)]):
        if name == "__init__" or name.startswith("_"):
            continue
            
        try:
            # Import the command module
            module_name = f"a2a.client.chat.commands.{name}"
            importlib.import_module(module_name)
            logger.debug(f"Loaded command module: {module_name}")
        except Exception as e:
            logger.error(f"Error loading command module {name}: {e}")

# Load all command modules when this package is imported
_discover_and_load_commands()