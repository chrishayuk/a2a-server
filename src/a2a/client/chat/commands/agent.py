#!/usr/bin/env python3
# a2a/client/chat/commands/agent.py
"""
Agent-related commands for the A2A client interface.
"""
import logging
import json
from typing import List, Dict, Any, Optional

from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax

# Import the registration function
from a2a.client.chat.commands import register_command

logger = logging.getLogger("a2a-client")

async def fetch_agent_card(base_url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the agent card from the server.
    
    Args:
        base_url: The base URL of the server
        
    Returns:
        The agent card data, or None if not found
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            url = f"{base_url}/agent-card.json"
            logger.debug(f"Fetching agent card from {url}")
            
            response = await client.get(url, timeout=3.0)
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                logger.debug(f"Agent card not available: {response.status_code}")
                return None
    except Exception as e:
        logger.debug(f"Error fetching agent card: {e}")
        return None

async def cmd_agent_card(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display the agent card for the current server.
    
    Usage: /agent_card [--raw]
    
    Options:
      --raw  Show the raw JSON of the agent card
    """
    console = Console()
    
    # Check if connected
    base_url = context.get("base_url")
    if not base_url:
        print("[yellow]Not connected to any server. Use /connect to connect.[/yellow]")
        return True
    
    # Check if we want raw output
    raw_mode = len(cmd_parts) > 1 and cmd_parts[1] == "--raw"
    
    # Check if we already have agent info
    agent_info = context.get("agent_info")
    
    if not agent_info:
        print(f"[dim]Fetching agent card from {base_url}/agent-card.json...[/dim]")
        agent_info = await fetch_agent_card(base_url)
        
        if agent_info:
            # Store in context for future use
            context["agent_info"] = agent_info
        else:
            print(f"[yellow]No agent card found at {base_url}/agent-card.json[/yellow]")
            return True
    
    # Display the agent card
    if raw_mode:
        # Show raw JSON
        json_str = json.dumps(agent_info, indent=2)
        console.print(Syntax(json_str, "json", theme="monokai", line_numbers=True))
        return True
    
    # Extract information
    agent_name = agent_info.get("name", "Unknown Agent")
    agent_version = agent_info.get("version", "Unknown")
    description = agent_info.get("description", "No description provided")
    capabilities = agent_info.get("capabilities", [])
    
    # Create a panel for the card
    content = f"# {agent_name}\n\n"
    
    if agent_version != "Unknown":
        content += f"**Version:** {agent_version}\n\n"
    
    content += f"{description}\n\n"
    
    if capabilities:
        content += "## Capabilities\n\n"
        for cap in capabilities:
            content += f"- {cap}\n"
    
    # Add any additional fields that might be present
    known_fields = {"name", "version", "description", "capabilities"}
    extra_fields = {k: v for k, v in agent_info.items() if k not in known_fields}
    
    if extra_fields:
        content += "\n## Additional Information\n\n"
        for key, value in extra_fields.items():
            if isinstance(value, (list, dict)):
                content += f"**{key}:** *complex data, use --raw to view*\n"
            else:
                content += f"**{key}:** {value}\n"
    
    console.print(Panel(
        Markdown(content),
        title="Agent Card",
        border_style="cyan",
        expand=False
    ))
    
    return True

# Register the commands
register_command("/agent_card", cmd_agent_card)
register_command("/agent", cmd_agent_card)  # Alias