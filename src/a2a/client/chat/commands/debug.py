#!/usr/bin/env python3
# a2a/client/chat/commands/debug.py
"""
Debug commands for the A2A client interface.
"""
import logging
import json
import sys
import os
import platform
import asyncio
import inspect
from typing import List, Dict, Any, Optional

from rich import print
from rich.panel import Panel
from rich.syntax import Syntax
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown

# Import the registration function
from a2a.client.chat.commands import register_command

# Import the A2A client
from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.spec import (
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
)

async def cmd_debug_info(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display detailed debug information about the current connection.
    
    Usage: /debug_info
    """
    console = Console()
    
    # Get server information
    base_url = context.get("base_url", "Not set")
    client = context.get("client")
    streaming_client = context.get("streaming_client")
    
    # Create debug panel
    print(Panel("Debug Information", style="red"))
    
    # Basic connection info
    print("[bold]Connection Details:[/bold]")
    print(f"Base URL: {base_url}")
    print(f"RPC URL: {base_url}/rpc")
    print(f"Events URL: {base_url}/events")
    print(f"Client available: {client is not None}")
    print(f"Streaming client available: {streaming_client is not None}")
    
    # System information
    print("\n[bold]System Information:[/bold]")
    print(f"Operating System: {platform.system()} {platform.release()}")
    print(f"Python version: {sys.version}")
    
    # Package versions
    print("\n[bold]Package Versions:[/bold]")
    try:
        import httpx
        print(f"HTTPX: {httpx.__version__}")
    except ImportError:
        print("HTTPX: Not installed")
    
    try:
        import rich
        print(f"Rich: {rich.__version__}")
    except ImportError:
        print("Rich: Not installed")
    
    try:
        import prompt_toolkit
        print(f"Prompt Toolkit: {prompt_toolkit.__version__}")
    except ImportError:
        print("Prompt Toolkit: Not installed")
    
    try:
        import typer
        print(f"Typer: {typer.__version__}")
    except ImportError:
        print("Typer: Not installed")
    
    # Transport details
    if client and hasattr(client, 'transport'):
        print("\n[bold]Transport Details:[/bold]")
        transport_type = type(client.transport).__name__
        print(f"Transport type: {transport_type}")
        
        if hasattr(client.transport, 'endpoint'):
            print(f"Transport endpoint: {client.transport.endpoint}")
            
        if hasattr(client.transport, 'sse_endpoint'):
            print(f"SSE endpoint: {client.transport.sse_endpoint}")
        
        # Additional transport details based on type
        if transport_type == "JSONRPCHTTPClient":
            print(f"Timeout: {client.transport._client.timeout if hasattr(client.transport, '_client') else 'Unknown'}")
        elif transport_type == "JSONRPCSSEClient":
            print(f"Alias endpoint: {client.transport.alias_endpoint if hasattr(client.transport, 'alias_endpoint') else 'Unknown'}")
            print(f"Pending response: {client.transport._pending_resp is not None if hasattr(client.transport, '_pending_resp') else 'Unknown'}")
    
    # Test server connection
    print("\n[bold]Testing Server Connection:[/bold]")
    if client:
        try:
            # First try agent-card.json
            print("Attempting to connect to agent-card.json...")
            try:
                import httpx
                async with httpx.AsyncClient() as http_client:
                    response = await http_client.get(f"{base_url}/agent-card.json", timeout=3.0)
                    print(f"Status code: {response.status_code}")
                    
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            print(f"Agent name: {data.get('name', 'Unknown')}")
                            print(f"Description: {data.get('description', 'Not provided')}")
                            print(f"Version: {data.get('version', 'Unknown')}")
                            
                            # Show capabilities if available
                            if 'capabilities' in data:
                                caps = data['capabilities']
                                print("\nAgent capabilities:")
                                for cap in caps:
                                    print(f"- {cap}")
                        except Exception as e:
                            print(f"Error parsing agent card: {e}")
                    else:
                        print("Agent card not available")
            except Exception as e:
                print(f"Error connecting to agent card: {e}")
            
            # Try RPC endpoint to check if it responds
            print("\nTesting RPC endpoint...")
            try:
                # Use a fake task ID to test the endpoint
                params = TaskQueryParams(id="debug-probe-000")
                try:
                    await client.get_task(params)
                except Exception as e:
                    # We expect an error, but the type of error tells us if the server is responding
                    if "not found" in str(e).lower() or "tasknotfound" in str(e).lower():
                        print("[green]RPC endpoint is responding correctly[/green]")
                    else:
                        print(f"[yellow]RPC endpoint responded with: {e}[/yellow]")
            except Exception as e:
                print(f"[red]Error testing RPC endpoint: {e}[/red]")
        except Exception as e:
            print(f"[red]Connection test error: {e}[/red]")
    
    # Available commands
    print("\n[bold]A2A Protocol Commands:[/bold]")
    table = Table(title="Available A2A Methods")
    table.add_column("Command", style="green")
    table.add_column("A2A Method")
    table.add_column("Status")
    
    # Check if methods are available
    methods = [
        ("/send", "tasks/send", "send_task"),
        ("/get", "tasks/get", "get_task"),
        ("/cancel", "tasks/cancel", "cancel_task"),
        ("/resubscribe", "tasks/resubscribe", "resubscribe"),
        ("/send_subscribe", "tasks/sendSubscribe", "send_subscribe")
    ]
    
    for cmd, method, client_method in methods:
        if client and hasattr(client, client_method):
            func = getattr(client, client_method)
            if callable(func):
                table.add_row(cmd, method, "[green]Available[/green]")
            else:
                table.add_row(cmd, method, "[yellow]Not callable[/yellow]")
        else:
            table.add_row(cmd, method, "[red]Not implemented[/red]")
    
    console.print(table)
    
    # Set debug mode
    context["debug_mode"] = True
    logging.getLogger("a2a-client").setLevel(logging.DEBUG)
    print("\n[green]Debug mode enabled. Detailed logs will be shown.[/green]")
    
    print("\n[bold]For additional help:[/bold]")
    print("- Use /connect to reconnect to the server")
    print("- Use /test_sse to test the SSE connection")
    print("- Use /help for available commands")
    print("- Try a simple task with /send hello")
    
    return True

async def cmd_test_sse(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Test SSE connection with the server.
    
    Usage: /test_sse [--timeout <seconds>]
    
    Example: /test_sse --timeout 10
    """
    base_url = context.get("base_url", "http://localhost:8000")
    rpc_url = base_url + "/rpc"
    events_url = base_url + "/events"
    
    # Parse timeout if provided
    timeout = 5.0
    if len(cmd_parts) > 2 and cmd_parts[1] == "--timeout":
        try:
            timeout = float(cmd_parts[2])
        except (ValueError, IndexError):
            print("[yellow]Invalid timeout value. Using default 5 seconds.[/yellow]")
    
    print(Panel(f"Testing SSE Connection to {events_url}", style="cyan"))
    
    # First, check the client configuration
    print("[bold]SSE Client Configuration:[/bold]")
    client = context.get("streaming_client")
    if client and hasattr(client, 'transport'):
        transport_type = type(client.transport).__name__
        print(f"Transport type: {transport_type}")
        
        if hasattr(client.transport, 'sse_endpoint'):
            print(f"Configured SSE endpoint: {client.transport.sse_endpoint}")
    else:
        print("[yellow]No streaming client available. Creating new one for test...[/yellow]")
    
    # Test direct HTTP connection to the events endpoint
    print("\n[bold]Testing HTTP Connection to Events Endpoint:[/bold]")
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            headers = {"Accept": "text/event-stream"}
            print(f"Sending GET request to {events_url}...")
            
            try:
                async with client.stream("GET", events_url, headers=headers, timeout=timeout) as response:
                    print(f"Response status: {response.status_code}")
                    print(f"Response headers: {dict(response.headers)}")
                    
                    if response.status_code == 200:
                        print("[green]SSE connection successful![/green]")
                        print(f"[yellow]Waiting for first event (will timeout after {timeout} seconds)...[/yellow]")
                        
                        try:
                            event_received = False
                            async for line in response.aiter_lines():
                                if line.strip():  # Only print non-empty lines
                                    print(f"Received: {line}")
                                    event_received = True
                                    break  # Just show the first line
                            
                            if event_received:
                                print("[green]Successfully received event data![/green]")
                            else:
                                print("[yellow]Connected, but no data was received.[/yellow]")
                        except httpx.ReadTimeout:
                            print("[yellow]No events received in timeout period, but connection was successful.[/yellow]")
                    else:
                        print(f"[red]Failed to connect to SSE endpoint. Status: {response.status_code}[/red]")
                        print(f"Response body: {await response.text()}")
            except Exception as e:
                print(f"[red]Error connecting to SSE endpoint: {e}[/red]")
    except ImportError:
        print("[red]httpx not installed. Cannot test SSE connection.[/red]")
    
    # Now test the actual client's streaming capability
    print("\n[bold]Testing A2A Client Streaming API:[/bold]")
    streaming_client = context.get("streaming_client")
    if not streaming_client:
        try:
            print(f"Creating new streaming client for {rpc_url} and {events_url}...")
            streaming_client = A2AClient.over_sse(rpc_url, events_url)
            context["streaming_client"] = streaming_client
        except Exception as e:
            print(f"[red]Failed to create streaming client: {e}[/red]")
            return True
    
    print("Testing stream() method...")
    try:
        # Use asyncio.wait_for to implement timeout
        async def _test_stream():
            async for msg in streaming_client.transport.stream():
                print(f"Received event: {msg}")
                return True  # Exit after first message
            return False
        
        try:
            result = await asyncio.wait_for(_test_stream(), timeout=timeout)
            if result:
                print("[green]Successfully received event from transport.stream()[/green]")
            else:
                print("[yellow]Stream ended without receiving any events[/yellow]")
        except asyncio.TimeoutError:
            print("[yellow]No events received within timeout period, but stream() is working[/yellow]")
        except Exception as e:
            print(f"[red]Error in stream() method: {e}[/red]")
    except Exception as e:
        print(f"[red]Failed to test stream method: {e}[/red]")
    
    # Set debug mode
    context["debug_mode"] = True
    logging.getLogger("a2a-client").setLevel(logging.DEBUG)
    logging.getLogger("a2a-client.sse").setLevel(logging.DEBUG)
    print("\n[green]Debug mode enabled for SSE. Detailed logs will be shown for future operations.[/green]")
    
    return True

async def cmd_test_send_subscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Test the sendSubscribe operation with diagnostic information.
    
    Usage: /test_send_subscribe <text>
    
    Example: /test_send_subscribe hello
    """
    if len(cmd_parts) < 2:
        print("[yellow]Error: No text provided. Usage: /test_send_subscribe <text>[/yellow]")
        return True
    
    # Enable debug mode
    context["debug_mode"] = True
    logging.getLogger("a2a-client").setLevel(logging.DEBUG)
    logging.getLogger("a2a-client.sse").setLevel(logging.DEBUG)
    
    print(Panel("Testing sendSubscribe Operation with Diagnostics", style="cyan"))
    
    # Extract text
    text = " ".join(cmd_parts[1:])
    
    # Get server information
    base_url = context.get("base_url", "http://localhost:8000")
    rpc_url = base_url + "/rpc"
    events_url = base_url + "/events"
    
    print("[bold]Connection Information:[/bold]")
    print(f"Base URL: {base_url}")
    print(f"RPC URL: {rpc_url}")
    print(f"Events URL: {events_url}")
    
    # Create a new SSE client specifically for this test
    try:
        print("\n[bold]Creating new SSE client...[/bold]")
        from a2a.client.a2a_client import A2AClient
        sse_client = A2AClient.over_sse(rpc_url, events_url)
        
        # Show client information
        print(f"Client type: {type(sse_client).__name__}")
        print(f"Transport type: {type(sse_client.transport).__name__}")
        
        if hasattr(sse_client.transport, 'endpoint'):
            print(f"Transport endpoint: {sse_client.transport.endpoint}")
        if hasattr(sse_client.transport, 'sse_endpoint'):
            print(f"SSE endpoint: {sse_client.transport.sse_endpoint}")
        if hasattr(sse_client.transport, 'alias_endpoint'):
            print(f"Alias endpoint: {sse_client.transport.alias_endpoint}")
    except Exception as e:
        print(f"[red]Error creating SSE client: {e}[/red]")
        return True
    
    # Create the task parameters
    print("\n[bold]Creating task parameters...[/bold]")
    from a2a.json_rpc.spec import TextPart, Message, TaskSendParams
    import uuid
    
    task_id = str(uuid.uuid4())
    part = TextPart(type="text", text=text)
    message = Message(role="user", parts=[part])
    params = TaskSendParams(id=task_id, sessionId=None, message=message)
    
    print(f"Task ID: {task_id}")
    print(f"Parameters: {params.model_dump(exclude_none=True)}")
    
    # Store in context for reference
    context["last_task_id"] = task_id
    
    console = Console()
    print(f"\n[bold]Sending task and subscribing to updates...[/bold]")
    print(f"Text: '{text}'")
    
    # Set up event tracking
    status_events = 0
    artifact_events = 0
    other_events = 0
    
    try:
        from rich.live import Live
        from rich.text import Text
        from a2a.client.ui.ui_helpers import format_status_event, format_artifact_event
        
        with Live("", refresh_per_second=4, console=console) as live:
            try:
                print(f"[dim]Calling send_subscribe method...[/dim]")
                
                # Start a timer
                import time
                start_time = time.time()
                
                async for evt in sse_client.send_subscribe(params):
                    elapsed = time.time() - start_time
                    
                    if hasattr(evt, "__class__"):
                        evt_type = evt.__class__.__name__
                    else:
                        evt_type = type(evt).__name__
                    
                    # Debug information
                    print(f"[dim]Received event type: {evt_type} at {elapsed:.2f}s[/dim]")
                    
                    if hasattr(evt, "status"):
                        status_events += 1
                        live.update(Text.from_markup(format_status_event(evt)))
                        
                        # Debug status information
                        if hasattr(evt.status, "state"):
                            print(f"[dim]Status state: {evt.status.state}[/dim]")
                        
                        # Check for final event
                        if hasattr(evt, "final") and evt.final:
                            print(f"[green]Task {task_id} completed after {elapsed:.2f}s with {status_events} status events and {artifact_events} artifact events[/green]")
                            break
                    elif hasattr(evt, "artifact"):
                        artifact_events += 1
                        live.update(Text.from_markup(format_artifact_event(evt)))
                        
                        # Debug artifact information
                        if hasattr(evt.artifact, "name"):
                            print(f"[dim]Artifact name: {evt.artifact.name}[/dim]")
                    else:
                        other_events += 1
                        live.update(Text(f"Unknown event at {elapsed:.2f}s: {evt_type}"))
                        
                        # Extra debug for unknown events
                        print(f"[dim]Unknown event data: {evt}[/dim]")
            except asyncio.CancelledError:
                print("\n[yellow]Operation interrupted.[/yellow]")
            except Exception as e:
                print(f"\n[red]Error during sendSubscribe: {e}[/red]")
                import traceback
                traceback.print_exc()
    except Exception as e:
        print(f"[red]Error setting up test: {e}[/red]")
    
    # Final report
    print("\n[bold]Test Results:[/bold]")
    print(f"Status Events: {status_events}")
    print(f"Artifact Events: {artifact_events}")
    print(f"Other Events: {other_events}")
    
    return True

# Register the commands
register_command("/debug_info", cmd_debug_info)
register_command("/test_sse", cmd_test_sse)
register_command("/test_send_subscribe", cmd_test_send_subscribe)