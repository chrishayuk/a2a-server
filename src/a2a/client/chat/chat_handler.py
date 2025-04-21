#!/usr/bin/env python3
# a2a/client/chat/chat_handler.py - with auto-connect feature
"""
Main chat handler for the A2A client interface.

Manages the chat loop, command processing, and UI interaction.
"""
import asyncio
import sys
import gc
import logging
import os
from rich import print
from rich.panel import Panel

# a2a client imports
from a2a.client.chat.chat_context import ChatContext
from a2a.client.chat.ui_manager import ChatUIManager
from a2a.client.ui.ui_helpers import display_welcome_banner, clear_screen, restore_terminal

logger = logging.getLogger("a2a-client")

async def auto_connect(ui_manager, chat_context):
    """
    Automatically connect to a default server on startup.
    
    Tries in this order:
    1. Use the provided base_url from command line
    2. Try to load a config file and use the first server
    3. Connect to http://localhost:8000 as fallback
    
    Args:
        ui_manager: The UI manager instance
        chat_context: The chat context instance
    """
    try:
        # If base_url is already set, we don't need to do anything
        if chat_context.base_url:
            logger.info(f"Using provided base_url: {chat_context.base_url}")
            from a2a.client.chat.commands.connection import cmd_connect
            context_dict = chat_context.to_dict()
            await cmd_connect(["/connect", chat_context.base_url], context_dict)
            chat_context.update_from_dict(context_dict)
            return True
        
        # Try to load config
        try:
            from a2a.client.chat.commands.connection import cmd_load_config, cmd_connect
            
            # Convert to dict for command handlers
            context_dict = chat_context.to_dict()
            
            # First try to load config to get servers
            await cmd_load_config(["/load_config"], context_dict)
            
            # If we found servers, connect to the first one
            if context_dict.get("server_names"):
                servers = context_dict.get("server_names", {})
                first_server_name = next(iter(servers.keys()))
                first_server_url = servers[first_server_name]
                
                logger.info(f"Auto-connecting to first server from config: {first_server_name} ({first_server_url})")
                
                # Connect to the first server
                await cmd_connect(["/connect", first_server_name], context_dict)
                
                # Update context with changes from commands
                chat_context.update_from_dict(context_dict)
                return True
        except Exception as e:
            logger.warning(f"Error during config loading/auto-connect: {e}")
        
        # Fallback: connect to localhost:8000
        logger.info("Auto-connecting to default server at http://localhost:8000")
        
        from a2a.client.chat.commands.connection import cmd_connect
        context_dict = chat_context.to_dict()
        await cmd_connect(["/connect", "http://localhost:8000"], context_dict)
        chat_context.update_from_dict(context_dict)
        return True
        
    except Exception as e:
        logger.error(f"Error during auto-connect: {e}")
        return False

async def handle_chat_mode(base_url=None, config_file=None):
    """
    Enter interactive chat mode for the A2A client.
    
    Args:
        base_url: Optional base URL for the A2A server
        config_file: Optional path to a configuration file
        
    Returns:
        True if chat mode exited normally, False otherwise
    """
    ui_manager = None
    exit_code = 0
    
    try:
        # Initialize chat context
        chat_context = ChatContext(base_url, config_file)
        
        if not await chat_context.initialize():
            print("[red]Failed to initialize chat context.[/red]")
            return False
            
        # Initialize UI manager
        ui_manager = ChatUIManager(chat_context)
        
        # Display welcome banner
        display_welcome_banner(chat_context.to_dict())
        
        # Auto-connect to a server
        await auto_connect(ui_manager, chat_context)
        
        # Main chat loop
        while True:
            try:
                # Get user input
                user_message = await ui_manager.get_user_input()
                
                # Handle empty messages
                if not user_message:
                    continue
                
                # Handle exit/quit commands
                if user_message.lower() in ["exit", "quit"]:
                    print(Panel("Exiting A2A client.", style="bold red"))
                    break
                
                # Handle special commands
                if user_message.startswith('/'):
                    # Process command and check if an exit was requested
                    await ui_manager.handle_command(user_message)
                    if chat_context.exit_requested:
                        break
                    continue
                
                # Display user message
                ui_manager.print_message(user_message, role="user")
                
                # Prepare to send a task
                cmd_parts = ["/send", user_message]
                context_dict = chat_context.to_dict()
                
                # Import the task commands module
                from a2a.client.chat.commands.tasks import cmd_send
                
                # Send the task (this will display the result automatically)
                await cmd_send(cmd_parts, context_dict)
                
                # Update the context with any changes
                chat_context.update_from_dict(context_dict)

            except KeyboardInterrupt:
                print("\n[yellow]Chat interrupted. Type 'exit' to quit.[/yellow]")
            except EOFError:
                # EOF (Ctrl+D) should exit cleanly
                print(Panel("EOF detected. Exiting A2A client.", style="bold red"))
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                print(f"[red]Error processing message:[/red] {e}")
                continue
    except asyncio.CancelledError:
        # Handle task cancellation gracefully
        print("[yellow]Chat task cancelled.[/yellow]")
    except Exception as e:
        logger.error(f"Error in chat mode: {e}", exc_info=True)
        print(f"[red]Error in chat mode:[/red] {e}")
        exit_code = 1
    finally:
        # Clean up all resources in order
        
        # 1. First clean up UI manager
        if ui_manager:
            try:
                await ui_manager.cleanup()
            except Exception as e:
                logger.error(f"Error during UI cleanup: {e}", exc_info=True)
        
        # 2. Restore terminal state
        restore_terminal()
        
        # 3. Force garbage collection to run before exit
        gc.collect()
    
    return exit_code == 0  # Return success status