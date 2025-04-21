#!/usr/bin/env python3
# a2a/client/chat/commands/tasks.py
"""
Task management commands for the A2A client interface.
Includes send, get, cancel, resubscribe, and sendSubscribe commands.
These commands map directly to A2A protocol methods for consistency.
"""
import uuid
import asyncio
import json
from typing import List, Dict, Any, Optional

from rich import print
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
from rich.text import Text
from rich.console import Console

# Import the registration function
from a2a.client.chat.commands import register_command

# Import the A2A client
from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.spec import (
    TextPart,
    Message,
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)

# Import UI helpers
from a2a.client.ui.ui_helpers import (
    display_task_info,
    format_status_event,
    format_artifact_event
)

# Define these helper functions directly in this file to avoid import issues
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
    content: List[str] = []
    for part in artifact.parts:
        # If text is present, render it directly
        if getattr(part, "text", None):
            content.append(part.text)
        # If part has a MIME type, show it plus a JSON dump
        elif getattr(part, "mime_type", None):
            content.append(f"[dim]MIME: {part.mime_type}[/dim]")
            try:
                content.append(json.dumps(part.model_dump(exclude_none=True), indent=2))
            except Exception:
                content.append(str(part))
        # Fallback: JSON dump of whatever fields exist, or str(part)
        else:
            try:
                content.append(json.dumps(part.model_dump(exclude_none=True), indent=2))
            except Exception:
                content.append(str(part))
    
    # Join all parts with blank lines
    display_text = "\n\n".join(content)
    
    console.print(Panel(
        display_text,
        title=f"Artifact: {name}",
        border_style="green"
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


async def cmd_send(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Send a task to the A2A server using tasks/send.
    
    Usage: /send <text>
    
    Example: /send Hello, please summarize this conversation
    """
    if len(cmd_parts) < 2:
        print("[yellow]Error: No text provided. Usage: /send <text>[/yellow]")
        return True
        
    # Get the client from context
    client = context.get("client")
    if not client:
        print("[red]Error: Not connected to a server. Use /connect first.[/red]")
        return True
        
    # Extract the text (everything after the command)
    text = " ".join(cmd_parts[1:])
    
    # Create the task parameters
    task_id = str(uuid.uuid4())
    part = TextPart(type="text", text=text)
    message = Message(role="user", parts=[part])
    params = TaskSendParams(id=task_id, sessionId=None, message=message)
    
    try:
        # Send the task
        print(f"[dim]Sending task with ID: {task_id}[/dim]")
        task = await client.send_task(params)
        
        # Store the task ID in context for easy reference
        context["last_task_id"] = task_id
        
        # Display the task information
        display_task_info(task)
        
        # Display artifacts if any
        if hasattr(task, "artifacts") and task.artifacts:
            print(f"\n[bold]Artifacts ({len(task.artifacts)}):[/bold]")
            display_task_artifacts(task)
        
        return True
    except Exception as e:
        print(f"[red]Error sending task: {e}[/red]")
        if context.get("debug_mode", False):
            import traceback
            traceback.print_exc()
        return True

async def cmd_get(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Get details about a task by ID using tasks/get.
    
    Usage: /get <id>
    
    Example: /get 123e4567-e89b-12d3-a456-426614174000
    """
    # Get the client from context
    client = context.get("client")
    if not client:
        print("[red]Error: Not connected to a server. Use /connect first.[/red]")
        return True
    
    # Determine task ID
    task_id = None
    if len(cmd_parts) > 1:
        task_id = cmd_parts[1]
    elif "last_task_id" in context:
        task_id = context["last_task_id"]
        print(f"[dim]Using last task ID: {task_id}[/dim]")
    else:
        print("[yellow]Error: No task ID provided and no previous task found.[/yellow]")
        return True
    
    try:
        # Get the task - using proper TaskQueryParams object
        params = TaskQueryParams(id=task_id)
        task = await client.get_task(params)
        
        # Create console for output
        console = Console()
        
        # Display the task information
        display_task_info(task, console=console)
        
        # Display task status message if available
        if hasattr(task, "status") and hasattr(task.status, "message") and task.status.message:
            message = task.status.message
            if hasattr(message, "parts") and message.parts:
                message_parts = []
                for part in message.parts:
                    if hasattr(part, "text") and part.text:
                        message_parts.append(part.text)
                
                if message_parts:
                    console.print(Panel(
                        "\n".join(message_parts),
                        title="Task Message",
                        border_style="blue"
                    ))
        
        # Display all artifacts
        if hasattr(task, "artifacts") and task.artifacts:
            print(f"\n[bold]Artifacts ({len(task.artifacts)}):[/bold]")
            for artifact in task.artifacts:
                display_artifact(artifact, console)
        
        return True
    except Exception as e:
        print(f"[red]Error getting task: {e}[/red]")
        if context.get("debug_mode", False):
            import traceback
            traceback.print_exc()
        return True
    
async def cmd_cancel(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Cancel a running task using tasks/cancel.
    
    Usage: /cancel <id>
    
    Example: /cancel 123e4567-e89b-12d3-a456-426614174000
    """
    # Get the client from context
    client = context.get("client")
    if not client:
        print("[red]Error: Not connected to a server. Use /connect first.[/red]")
        return True
    
    # Determine task ID
    task_id = None
    if len(cmd_parts) > 1:
        task_id = cmd_parts[1]
    elif "last_task_id" in context:
        task_id = context["last_task_id"]
        print(f"[dim]Using last task ID: {task_id}[/dim]")
    else:
        print("[yellow]Error: No task ID provided and no previous task found.[/yellow]")
        return True
    
    try:
        # Cancel the task - using proper TaskIdParams object
        params = TaskIdParams(id=task_id)
        await client.cancel_task(params)
        
        print(f"[green]Successfully cancelled task {task_id}[/green]")
        
        # Get the latest task status
        await cmd_get(["/get", task_id], context)
        
        return True
    except Exception as e:
        print(f"[red]Error cancelling task: {e}[/red]")
        if context.get("debug_mode", False):
            import traceback
            traceback.print_exc()
        return True

async def cmd_resubscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Watch status and artifact updates for an existing task using tasks/resubscribe.
    
    Usage: /resubscribe <id>
    
    Example: /resubscribe 123e4567-e89b-12d3-a456-426614174000
    """
    # Get the client from context
    client = context.get("client")
    if not client:
        print("[red]Error: Not connected to a server. Use /connect first.[/red]")
        return True
    
    # Determine task ID
    task_id = None
    if len(cmd_parts) > 1:
        task_id = cmd_parts[1]
    elif "last_task_id" in context:
        task_id = context["last_task_id"]
        print(f"[dim]Using last task ID: {task_id}[/dim]")
    else:
        print("[yellow]Error: No task ID provided and no previous task found.[/yellow]")
        return True
    
    # Set up SSE client if needed
    if not hasattr(client, "transport") or not hasattr(client.transport, "stream"):
        print("[yellow]Client does not support streaming. Creating a new streaming client...[/yellow]")
        
        base_url = context.get("base_url", "http://localhost:8000")
        rpc_url = base_url + "/rpc"
        events_url = base_url + "/events"
        
        try:
            client = A2AClient.over_sse(rpc_url, events_url)
            context["streaming_client"] = client
        except Exception as e:
            print(f"[red]Error creating streaming client: {e}[/red]")
            if context.get("debug_mode", False):
                import traceback
                traceback.print_exc()
            return True
    else:
        # Use existing client
        client = context.get("streaming_client", client)
    
    console = Console()
    print(f"[dim]Resubscribing to task {task_id}. Press Ctrl+C to stop...[/dim]")
    
    try:
        # Create parameters and start watching - using proper TaskQueryParams object
        params = TaskQueryParams(id=task_id)
        
        # Store artifacts for displaying after completion
        all_artifacts = []
        final_status = None
        
        with Live("", refresh_per_second=4, console=console) as live:
            try:
                async for evt in client.resubscribe(params):
                    if isinstance(evt, TaskStatusUpdateEvent):
                        live.update(Text.from_markup(format_status_event(evt)))
                        
                        # Store the final status
                        if evt.final:
                            final_status = evt.status
                            
                        # If this is the final update, break
                        if evt.final:
                            break
                    elif isinstance(evt, TaskArtifactUpdateEvent):
                        live.update(Text.from_markup(format_artifact_event(evt)))
                        
                        # Store the artifact for later display
                        all_artifacts.append(evt.artifact)
                    else:
                        # Unknown event type
                        live.update(Text(f"Unknown event: {type(evt).__name__}"))
            except asyncio.CancelledError:
                print("\n[yellow]Watch interrupted.[/yellow]")
            except Exception as e:
                print(f"\n[red]Error watching task: {e}[/red]")
                if context.get("debug_mode", False):
                    import traceback
                    traceback.print_exc()
        
        # Display completion message
        if final_status:
            print(f"[green]Task {task_id} completed.[/green]")
            
            # Display final status message if available
            if hasattr(final_status, "message") and final_status.message and hasattr(final_status.message, "parts"):
                for part in final_status.message.parts:
                    if hasattr(part, "text") and part.text:
                        # Display the assistant's response in a panel
                        console.print(Panel(
                            part.text,
                            title="Response",
                            border_style="blue"
                        ))
        
        # Display all artifacts
        if all_artifacts:
            print(f"\n[bold]Artifacts ({len(all_artifacts)}):[/bold]")
            for artifact in all_artifacts:
                display_artifact(artifact, console)
        
        return True
    except KeyboardInterrupt:
        print("\n[yellow]Watch interrupted.[/yellow]")
        return True
    except Exception as e:
        print(f"[red]Error setting up watch: {e}[/red]")
        if context.get("debug_mode", False):
            import traceback
            traceback.print_exc()
        return True

async def cmd_send_subscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Send a task and subscribe to its updates using tasks/sendSubscribe.

    Usage: /send_subscribe <text>
    """
    if len(cmd_parts) < 2:
        print("[yellow]Error: No text provided. Usage: /send_subscribe <text>[/yellow]")
        return True

    text = " ".join(cmd_parts[1:])

    # 1) Ensure we have an HTTP client (with the correct /rpc URL)
    http_client = context.get("client")
    base_url = context.get("base_url", "http://localhost:8000")
    rpc_url = base_url.rstrip("/") + "/rpc"
    if not http_client:
        try:
            http_client = A2AClient.over_http(rpc_url)
            context["client"] = http_client
        except Exception as e:
            print(f"[red]Error creating HTTP client: {e}[/red]")
            if context.get("debug_mode"):
                import traceback; traceback.print_exc()
            return True

    # 2) Ensure we have a streaming client (with the correct /events URL)
    sse_client = context.get("streaming_client")
    events_url = base_url.rstrip("/") + "/events"
    if not sse_client:
        try:
            print(f"[dim]Initializing SSE client for {events_url}...[/dim]")
            sse_client = A2AClient.over_sse(rpc_url, events_url)
            context["streaming_client"] = sse_client
            print(f"[green]SSE client initialized[/green]")
        except Exception as e:
            print(f"[yellow]Warning: Could not initialize SSE client: {e}[/yellow]")
            print(f"[yellow]Streaming will fall back to non‑streaming mode[/yellow]")
            sse_client = None

    # 3) Build the send parameters
    task_id = str(uuid.uuid4())
    part = TextPart(type="text", text=text)
    message = Message(role="user", parts=[part])
    params = TaskSendParams(id=task_id, sessionId=None, message=message)
    context["last_task_id"] = task_id

    console = Console()
    print(f"[dim]Sending task with ID: {task_id}[/dim]")

    try:
        # Send the initial task via HTTP RPC
        task = await http_client.send_task(params)
        display_task_info(task)
    except Exception as e:
        print(f"[red]Error sending task: {e}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
        return True

    # 4) If we have an SSE client, stream updates
    if sse_client:
        print(f"[dim]Subscribing to updates. Press Ctrl+C to stop...[/dim]")
        all_artifacts = []
        final_status = None

        try:
            from rich.live import Live
            from rich.text import Text
            from a2a.client.ui.ui_helpers import format_status_event, format_artifact_event

            with Live("", refresh_per_second=4, console=console) as live:
                async for evt in sse_client.send_subscribe(params):
                    if isinstance(evt, TaskStatusUpdateEvent):
                        live.update(Text.from_markup(format_status_event(evt)))
                        if evt.final:
                            final_status = evt.status
                            break
                    elif isinstance(evt, TaskArtifactUpdateEvent):
                        live.update(Text.from_markup(format_artifact_event(evt)))
                        all_artifacts.append(evt.artifact)
                    else:
                        live.update(Text(f"Unknown event: {type(evt).__name__}"))
        except KeyboardInterrupt:
            print("\n[yellow]Subscription interrupted.[/yellow]")
        except Exception as e:
            print(f"\n[red]Error during streaming: {e}[/red]")
            if context.get("debug_mode"):
                import traceback; traceback.print_exc()

        # 5) Final output
        if final_status:
            print(f"[green]Task {task_id} completed.[/green]")
            if final_status.message and final_status.message.parts:
                for part in final_status.message.parts:
                    if part.text:
                        console.print(Panel(part.text, title="Response", border_style="blue"))

        if all_artifacts:
            print(f"\n[bold]Artifacts ({len(all_artifacts)}):[/bold]")
            for art in all_artifacts:
                display_artifact(art, console)

    return True

   
# Register all commands in this module with names that match A2A protocol methods
register_command("/send", cmd_send)
register_command("/get", cmd_get)
register_command("/cancel", cmd_cancel)
register_command("/resubscribe", cmd_resubscribe)
register_command("/send_subscribe", cmd_send_subscribe)

# Register aliases for backward compatibility
register_command("/watch", cmd_resubscribe)          # Alias for /resubscribe
register_command("/sendsubscribe", cmd_send_subscribe)  # No underscore variant
register_command("/watch_text", cmd_send_subscribe)     # Old alias