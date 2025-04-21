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
    """
    try:
        # 1) If base_url was passed in, use it
        if chat_context.base_url:
            logger.info(f"Using provided base_url: {chat_context.base_url}")
            from a2a.client.chat.commands.connection import cmd_connect
            ctx = chat_context.to_dict()
            await cmd_connect(["/connect", chat_context.base_url], ctx)
            chat_context.update_from_dict(ctx)
            return True

        # 2) Otherwise try loading config to find servers
        from a2a.client.chat.commands.connection import cmd_load_config, cmd_connect
        ctx = chat_context.to_dict()
        await cmd_load_config(["/load_config"], ctx)

        if ctx.get("server_names"):
            first_name = next(iter(ctx["server_names"]))
            logger.info(f"Auto-connecting to {first_name}")
            await cmd_connect(["/connect", first_name], ctx)
            chat_context.update_from_dict(ctx)
            return True

        # 3) Fallback
        logger.info("Auto-connecting to default http://localhost:8000")
        await cmd_connect(["/connect", "http://localhost:8000"], ctx)
        chat_context.update_from_dict(ctx)
        return True

    except Exception as e:
        logger.error(f"Error during auto-connect: {e}")
        return False


async def handle_chat_mode(base_url=None, config_file=None):
    """
    Enter interactive chat mode for the A2A client.

    Workflow:
      1. Initialize ChatContext (loads config, sets base_url)
      2. UI setup & welcome banner
      3. Auto‑connect to a server (runs /connect)
      4. Loop: read user input → send or send_subscribe
    """
    ui_manager = None
    exit_code = 0

    try:
        # 1) Initialize context
        chat_context = ChatContext(base_url, config_file)
        if not await chat_context.initialize():
            print("[red]Failed to initialize chat context.[/red]")
            return False

        # 2) UI setup
        ui_manager = ChatUIManager(chat_context)
        display_welcome_banner(chat_context.to_dict())

        # 3) Auto‑connect (runs /connect, fetches agent-card)
        await auto_connect(ui_manager, chat_context)

        # 4) Main loop
        while True:
            try:
                user_message = await ui_manager.get_user_input()
                if not user_message:
                    continue

                # Exit commands
                if user_message.lower() in ("exit", "quit"):
                    print(Panel("Exiting A2A client.", style="bold red"))
                    break

                # Slash commands (like /get, /cancel, etc.)
                if user_message.startswith("/"):
                    await ui_manager.handle_command(user_message)
                    if chat_context.exit_requested:
                        break
                    continue

                # Free‑form text → choose between send or send_subscribe
                ui_manager.print_message(user_message, role="user")
                ctx = chat_context.to_dict()

                # Check both advertised capability and existing SSE client
                caps = ctx.get("agent_info", {}).get("capabilities", [])
                has_stream_cap = "tasks/sendSubscribe" in caps
                has_sse_client = bool(ctx.get("streaming_client"))

                if has_stream_cap or has_sse_client:
                    from a2a.client.chat.commands.tasks import cmd_send_subscribe as send_cmd
                    cmd_name = "/send_subscribe"
                else:
                    from a2a.client.chat.commands.tasks import cmd_send as send_cmd
                    cmd_name = "/send"

                # Execute
                await send_cmd([cmd_name, user_message], ctx)
                chat_context.update_from_dict(ctx)

            except KeyboardInterrupt:
                print("\n[yellow]Chat interrupted. Type 'exit' to quit.[/yellow]")
            except EOFError:
                print(Panel("EOF detected. Exiting A2A client.", style="bold red"))
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                print(f"[red]Error processing message:[/red] {e}")
                continue

    except Exception as e:
        logger.error(f"Error in chat mode: {e}", exc_info=True)
        print(f"[red]Error in chat mode:[/red] {e}")
        exit_code = 1

    finally:
        if ui_manager:
            try:
                await ui_manager.cleanup()
            except Exception as e:
                logger.error(f"Error during UI cleanup: {e}", exc_info=True)
        restore_terminal()

    return exit_code == 0
