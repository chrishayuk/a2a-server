#!/usr/bin/env python3
# a2a/client/ui/ui_helpers.py
"""
UI helper functions for A2A client display and formatting.
"""
import os
import platform
import sys
from typing import Dict, Any, Optional, List

# rich imports
from rich import print
from rich.panel import Panel
from rich.markdown import Markdown
from rich.console import Console
from rich.table import Table
from rich.text import Text

# Import color constants
from a2a.client.ui.colors import *

def display_welcome_banner(context: Dict[str, Any], console: Optional[Console] = None) -> None:
    """
    Display the welcome banner with current connection info.
    
    Args:
        context: The current context with connection information
        console: Optional Console instance
    """
    if console is None:
        console = Console()
        
    base_url = context.get("base_url", "http://localhost:8000")
    
    # Create the panel content with explicit styling
    welcome_text = "Welcome to A2A Client!\n\n"
    connection_line = f"[{TEXT_DEEMPHASIS}]Connected to: {base_url}[/{TEXT_DEEMPHASIS}]\n\n"
    exit_line = f"Type [{TEXT_EMPHASIS}]'exit'[/{TEXT_EMPHASIS}] to quit or [{TEXT_EMPHASIS}]'/help'[/{TEXT_EMPHASIS}] for commands."
    
    # Combine the content with proper styling
    panel_content = welcome_text + connection_line + exit_line
    
    # Print welcome banner with current connection info
    console.print(Panel(
        panel_content,
        title="Welcome to A2A Client",
        title_align="center",
        expand=True,
        border_style=BORDER_PRIMARY
    ))

def display_markdown_panel(content: str, title: Optional[str] = None, style: str = TEXT_INFO) -> None:
    """
    Display content in a rich panel with markdown formatting.
    
    Args:
        content: The markdown content to display.
        title: Optional panel title.
        style: Color style for the panel.
    """
    console = Console()
    console.print(Panel(
        Markdown(content),
        title=title,
        style=style
    ))

def display_task_info(task: Any, color: bool = True, console: Optional[Console] = None) -> None:
    """
    Display task information in a nicely formatted panel.
    
    Args:
        task: The task object to display
        color: Whether to use color in the output
        console: Optional Console instance
    """
    if console is None:
        console = Console()
        
    # Format task status with color
    state = task.status.state.value
    status_style = {
        "pending": TEXT_WARNING,
        "running": TEXT_INFO,
        "completed": TEXT_SUCCESS,
        "cancelled": TEXT_DEEMPHASIS,
        "failed": TEXT_ERROR
    }.get(state.lower(), TEXT_NORMAL)
    
    # Build task details
    details = []
    details.append(f"Task ID: {task.id}")
    details.append(f"Status: [{status_style}]{state}[/{status_style}]")
    
    # Add message if available
    if task.status.message and task.status.message.parts:
        message = task.status.message.parts[0].text
        if message:
            details.append(f"Message: {message}")
    
    # Format artifacts
    if task.artifacts:
        details.append("\nArtifacts:")
        for art in task.artifacts:
            details.append(f"  • [{ARTIFACT_COLOR}]{art.name or '<unnamed>'}[/{ARTIFACT_COLOR}]")
            for p in art.parts:
                if hasattr(p, "text"):
                    text = p.text[:200] + "..." if len(p.text) > 200 else p.text
                    details.append(f"    {text}")
    
    # Build and display the panel
    panel_content = "\n".join(details)
    console.print(Panel(
        panel_content,
        title=f"Task Details",
        border_style=BORDER_SECONDARY
    ))

def format_status_event(event: Any) -> str:
    """Format a status update event for display."""
    state = event.status.state.value
    msg = ""
    if event.status.message and event.status.message.parts:
        msg = f" — {event.status.message.parts[0].text}"
    
    status_style = {
        "pending": TEXT_WARNING,
        "running": TEXT_INFO,
        "completed": TEXT_SUCCESS,
        "cancelled": TEXT_DEEMPHASIS,
        "failed": TEXT_ERROR
    }.get(state.lower(), TEXT_NORMAL)
    
    return f"[{STATUS_UPDATE_COLOR}]Status:[/{STATUS_UPDATE_COLOR}] [{status_style}]{state}{msg}[/{status_style}]"

def format_artifact_event(event: Any) -> str:
    """Format an artifact update event for display."""
    name = event.artifact.name or "<unnamed>"
    parts = []
    
    for part in event.artifact.parts:
        if hasattr(part, "text"):
            text = part.text[:200] + "..." if len(part.text) > 200 else part.text
            parts.append(f"  {text}")
        else:
            parts.append(f"  [dim]{type(part).__name__} data[/dim]")
    
    return f"[{ARTIFACT_UPDATE_COLOR}]Artifact: {name}[/{ARTIFACT_UPDATE_COLOR}]\n" + "\n".join(parts)

def clear_screen() -> None:
    """Clear the terminal screen in a cross-platform way."""
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")

def restore_terminal() -> None:
    """Best‑effort attempt to reset the TTY."""
    if sys.platform != "win32":
        os.system("stty sane")

def format_artifact_event(event: Any) -> str:
    """
    Format an artifact update event for display.
    
    Args:
        event: The artifact update event
        
    Returns:
        A string with rich formatting markup
    """
    name = event.artifact.name or "<unnamed>"
    parts_text = []
    
    # Process each part in the artifact
    for part in event.artifact.parts:
        if hasattr(part, "text"):
            text = part.text[:200] + "..." if len(part.text) > 200 else part.text
            parts_text.append(f"  {text}")
        elif hasattr(part, "mime_type"):
            parts_text.append(f"  [dim]Content with MIME type: {part.mime_type}[/dim]")
        else:
            parts_text.append(f"  [dim]{type(part).__name__} data[/dim]")
    
    return f"[{ARTIFACT_COLOR}]Artifact: {name}[/{ARTIFACT_COLOR}]\n" + "\n".join(parts_text)

def display_artifact(artifact: Any, console: Optional[Console] = None) -> None:
    """
    Display an artifact in a rich panel.
    
    Args:
        artifact: The artifact to display
        console: Optional Console instance
    """
    if console is None:
        console = Console()
    
    name = artifact.name or "<unnamed>"
    
    # Build content for each part
    content = []
    for part in artifact.parts:
        if hasattr(part, "text"):
            content.append(part.text)
        elif hasattr(part, "mime_type"):
            content.append(f"[dim]Content with MIME type: {part.mime_type}[/dim]")
        else:
            content.append(f"[dim]{type(part).__name__} data[/dim]")
    
    # Join all parts with newlines
    display_text = "\n\n".join(content)
    
    # Create panel
    console.print(Panel(
        display_text,
        title=f"Artifact: {name}",
        border_style=ARTIFACT_COLOR
    ))

def display_task_artifacts(task: Any, console: Optional[Console] = None) -> None:
    """
    Display all artifacts in a task.
    
    Args:
        task: The task containing artifacts
        console: Optional Console instance
    """
    if console is None:
        console = Console()
    
    # Check if task has artifacts
    if not hasattr(task, "artifacts") or not task.artifacts:
        return
    
    # Display each artifact
    for artifact in task.artifacts:
        display_artifact(artifact, console)