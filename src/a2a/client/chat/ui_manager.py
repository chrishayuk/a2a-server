#!/usr/bin/env python3
# a2a/client/chat/ui_manager.py
"""
UI Manager for the A2A client chat interface.

Handles the chat UI, status displays, and user interaction.
"""
import os
import json
import time
import signal
import asyncio
from types import FrameType
from typing import Optional, List, Dict, Any

from rich import print
from rich.markdown import Markdown
from rich.panel import Panel
from rich.console import Console
from rich.live import Live
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

# a2a client imports
from a2a.client.chat.command_completer import ChatCommandCompleter
from a2a.client.chat.commands import handle_command
from a2a.client.ui.colors import *

class ChatUIManager:
    """
    Manage the chat UI and user interaction.
    
    Handles command input, task status display, and event streaming visuals.
    """

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    def __init__(self, context):
        """
        Initialize the UI manager.
        
        Args:
            context: The chat context object
        """
        self.context = context
        self.console = Console()

        # ui / mode flags
        self.task_running = False
        self.interrupt_requested = False

        # task timing
        self.task_start_time = None

        # live spinner
        self.live_display: Optional[Live] = None
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼",
                               "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0

        # SIGINT handling
        self._prev_sigint_handler: Optional[signal.Handlers] = None

        # prompt‑toolkit
        history_file = os.path.expanduser("~/.a2a_chat_history")
        style = Style.from_dict({
            "completion-menu": "bg:default",
            "completion-menu.completion": "bg:default fg:goldenrod",
            "completion-menu.completion.current": "bg:default fg:goldenrod bold",
            "auto-suggestion": "fg:ansibrightblack",
        })
        self.session = PromptSession(
            history=FileHistory(history_file),
            auto_suggest=AutoSuggestFromHistory(),
            completer=ChatCommandCompleter(context.to_dict()),
            complete_while_typing=True,
            style=style,
            message="> ",
        )

        # misc
        self.last_input = None

    # ------------------------------------------------------------------ #
    # low‑level helpers
    # ------------------------------------------------------------------ #
    def _get_spinner_char(self) -> str:
        """Get the next spinner character in the animation sequence."""
        char = self.spinner_frames[self.spinner_idx]
        self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_frames)
        return char

    # ----- SIGINT helpers ------------------------------------------------
    def _install_sigint_handler(self) -> None:
        """Replace SIGINT handler so first ^C only cancels current operations."""
        if self._prev_sigint_handler is not None:
            return  # already installed

        self._prev_sigint_handler = signal.getsignal(signal.SIGINT)

        def _handler(sig: int, frame: Optional[FrameType]) -> None:
            if self.task_running:
                if not self.interrupt_requested:
                    self.interrupt_requested = True
                    print("\n[yellow]Interrupt requested – waiting for "
                          "current task to complete...[/yellow]")
                    self._interrupt_now()
                    return
                # second Ctrl‑C: fall through
            if callable(self._prev_sigint_handler):
                self._prev_sigint_handler(sig, frame)

        signal.signal(signal.SIGINT, _handler)

    def _restore_sigint_handler(self) -> None:
        """Restore the original SIGINT handler."""
        if self._prev_sigint_handler is not None:
            signal.signal(signal.SIGINT, self._prev_sigint_handler)
            self._prev_sigint_handler = None

    # ------------------------------------------------------------------ #
    # helper: cancel current operations
    # ------------------------------------------------------------------ #
    def _interrupt_now(self) -> None:
        """
        Invoked on the *first* Ctrl‑C (or `/interrupt` command).

        • Stops the spinner / Live display immediately  
        • Clears all timing state so the next turn starts fresh  
        • Restores the original SIGINT handler so a second Ctrl‑C exits the app
        """
        # Halt the animated compact view, if active
        if self.live_display:
            self.live_display.stop()
            self.live_display = None

        # Reset runtime flags & timers
        self.task_running = False
        self.task_start_time = None
        self.interrupt_requested = False  # <- allow future task runs

        # Give Ctrl‑C its normal behaviour back
        self._restore_sigint_handler()

    # ------------------------------------------------------------------ #
    # user input
    # ------------------------------------------------------------------ #
    async def get_user_input(self) -> str:
        """
        Get input from the user.
        
        Returns:
            The user's input string
        """
        user_message = await self.session.prompt_async()
        self.last_input = user_message.strip()
        
        # Add to command history if it's a command
        if self.last_input.startswith("/"):
            context_dict = self.context.to_dict()
            if "command_history" in context_dict:
                context_dict["command_history"].append(self.last_input)
            self.context.update_from_dict(context_dict)
        
        # Clear the line for clean display
        print("\r" + " " * (len(self.last_input) + 2), end="\r")
        return self.last_input

    # ------------------------------------------------------------------ #
    # message / status rendering
    # ------------------------------------------------------------------ #
    def print_message(self, message: str, role: str = "user") -> None:
        """
        Print a message from the user or system.
        
        Args:
            message: The message content
            role: The role of the message sender ('user' or 'system')
        """
        style = USER_COLOR if role == "user" else TEXT_INFO
        title = "You" if role == "user" else "System"
        
        print(Panel(message or "[No Message]",
                   style=style, title=title))
                   
        if role == "user":
            # Reset the task state for new user message
            self.task_running = False
            self.task_start_time = None
            
            if self.live_display:
                self.live_display.stop()
                self.live_display = None

    def start_task_spinner(self, task_id: str) -> None:
        """
        Start the animated spinner for a running task.
        
        Args:
            task_id: The ID of the task being watched
        """
        if self.live_display:
            self.live_display.stop()
            
        self.task_running = True
        self.task_start_time = time.time()
        self._install_sigint_handler()
        
        self.live_display = Live("", refresh_per_second=4, console=self.console)
        self.live_display.start()
        
        print("[dim italic]Press Ctrl+C to interrupt task execution[/dim italic]", end="\r")

    def update_task_status(self, status: str, message: str = "") -> None:
        """
        Update the displayed task status.
        
        Args:
            status: The status string
            message: Optional status message
        """
        if not self.live_display:
            self.start_task_spinner("<unknown>")
            
        # Determine status style
        status_style = {
            "pending": TEXT_WARNING,
            "running": TEXT_INFO,
            "completed": TEXT_SUCCESS,
            "cancelled": TEXT_DEEMPHASIS,
            "failed": TEXT_ERROR
        }.get(status.lower(), TEXT_NORMAL)
        
        # Calculate elapsed time
        now = time.time()
        elapsed = int(now - self.task_start_time) if self.task_start_time else 0
        
        # Get spinner char
        spinner = self._get_spinner_char()
        
        # Create the display
        display_text = f"[dim]Task status ({elapsed}s): {spinner}[/dim] "
        display_text += f"[{status_style}]{status}[/{status_style}]"
        
        if message:
            display_text += f" - {message}"
            
        self.live_display.update(Text.from_markup(display_text))

    def stop_task_display(self, final_status: str = "completed") -> None:
        """
        Stop the task display and show completion information.
        
        Args:
            final_status: The final status of the task
        """
        if self.live_display:
            self.live_display.stop()
            self.live_display = None
            
        if self.task_start_time:
            elapsed = time.time() - self.task_start_time
            print(f"[dim]Task {final_status} in {elapsed:.2f}s[/dim]")
            
        self.task_running = False
        self.task_start_time = None
        self._restore_sigint_handler()

    # ------------------------------------------------------------------ #
    # command handling
    # ------------------------------------------------------------------ #
    async def handle_command(self, command: str) -> bool:
        """
        Handle a command.
        
        Args:
            command: The command string
            
        Returns:
            True if the command was handled, False otherwise
        """
        context_dict = self.context.to_dict()
        handled = await handle_command(command, context_dict)
        self.context.update_from_dict(context_dict)
        return handled

    # ------------------------------------------------------------------ #
    # cleanup
    # ------------------------------------------------------------------ #
    async def cleanup(self) -> None:
        """Clean up resources and reset the terminal."""
        if self.live_display:
            self.live_display.stop()
            self.live_display = None
            
        self._restore_sigint_handler()
        
        # Close any active clients
        await self.context.close()