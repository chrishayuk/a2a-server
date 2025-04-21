#!/usr/bin/env python3
# a2a/client/chat/command_completer.py
"""
Command completion for the A2A client interface.
"""
from prompt_toolkit.completion import Completer, Completion
from typing import List, Iterable

# a2a client imports
from a2a.client.chat.commands import get_command_completions

class ChatCommandCompleter(Completer):
    """
    Completer for chat commands with slash prefix.
    
    Provides command completion for A2A client commands,
    supporting both command names and command arguments.
    """
    
    def __init__(self, context):
        """
        Initialize the completer with the current chat context.
        
        Args:
            context: The current chat context with server and client information
        """
        self.context = context
        
    def get_completions(self, document, complete_event) -> Iterable[Completion]:
        """
        Get completions for the current document.
        
        Args:
            document: The current input document
            complete_event: The completion event
            
        Returns:
            Iterable of Completion objects
        """
        text = document.text
        
        # Only suggest completions for slash commands
        if text.lstrip().startswith('/'):
            word_before_cursor = document.get_word_before_cursor()
            
            # Get completions from command system
            completions = get_command_completions(text.lstrip())
            
            for completion in completions:
                # If completion already matches what's there, don't suggest it
                if text.lstrip() == completion:
                    continue
                    
                # For simple command completion, just return the command
                if ' ' not in completion:
                    yield Completion(
                        completion, 
                        start_position=-len(text.lstrip()),
                        style='fg:goldenrod'
                    )
                # For argument completion, provide the full arg
                else:
                    yield Completion(
                        completion.split()[-1], 
                        start_position=-len(word_before_cursor),
                        style='fg:goldenrod'
                    )