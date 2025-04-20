# File: a2a/server/agent_card.py
"""
Agent Card implementation for the A2A Protocol.

This module handles the creation and serving of agent cards compliant with the A2A Protocol.
"""
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class ProviderInfo(BaseModel):
    """Provider information for an agent card."""
    organization: str
    url: str

class Capabilities(BaseModel):
    """Capabilities of an agent."""
    streaming: bool = True
    pushNotifications: bool = False
    stateTransitionHistory: bool = False

class Authentication(BaseModel):
    """Authentication requirements for an agent."""
    schemes: List[str]
    credentials: Optional[str] = None

class Skill(BaseModel):
    """Skill description for an agent card."""
    id: str
    name: str
    description: str
    tags: List[str]
    examples: Optional[List[str]] = None
    inputModes: Optional[List[str]] = None
    outputModes: Optional[List[str]] = None

class AgentCard(BaseModel):
    """A2A Protocol compliant agent card."""
    name: str
    description: str
    url: str
    version: str
    provider: Optional[ProviderInfo] = None
    documentationUrl: Optional[str] = None
    capabilities: Capabilities
    authentication: Authentication
    defaultInputModes: List[str]
    defaultOutputModes: List[str]
    skills: List[Skill]

def create_agent_card(
    handler_name: str,
    base_url: str,
    handler_config: Dict[str, Any]
) -> AgentCard:
    """
    Create an agent card for a handler using its configuration and dynamic info.
    
    Args:
        handler_name: The handler's name
        base_url: Base URL for the server
        handler_config: Configuration for the handler from YAML
        
    Returns:
        An AgentCard instance
    """
    # Extract agent_card section from config, defaulting to empty dict
    config_card = handler_config.get("agent_card", {})
    
    # Determine URL for this handler
    handler_url = f"{base_url}/{handler_name}"
    
    # Create default capabilities based on server capabilities
    capabilities = Capabilities(
        streaming=True,  # Assume streaming is supported
        pushNotifications=False,  # Default to no push notifications
        stateTransitionHistory=False  # Default to no state transition history
    )
    
    # Override with config if provided
    if "capabilities" in config_card:
        capabilities = Capabilities(**config_card["capabilities"])
    
    # Default authentication - no authentication required
    authentication = config_card.get("authentication", {
        "schemes": ["None"]
    })
    
    # Default input/output modes if not provided
    default_input_modes = config_card.get("defaultInputModes", ["text/plain"])
    default_output_modes = config_card.get("defaultOutputModes", ["text/plain"])
    
    # Default skills if not provided
    skills = config_card.get("skills", [])
    if not skills:
        # Create a default skill based on handler name
        skills = [{
            "id": f"{handler_name}-default",
            "name": handler_name.replace("_", " ").title(),
            "description": f"Default capability for {handler_name}",
            "tags": [handler_name],
            "examples": []
        }]
    
    # Create the agent card
    card = AgentCard(
        name=config_card.get("name", handler_name.replace("_", " ").title()),
        description=config_card.get("description", f"A2A handler for {handler_name}"),
        url=config_card.get("url", handler_url),
        version=config_card.get("version", "1.0.0"),
        provider=ProviderInfo(**config_card["provider"]) if "provider" in config_card else None,
        documentationUrl=config_card.get("documentationUrl"),
        capabilities=capabilities,
        authentication=Authentication(**authentication),
        defaultInputModes=default_input_modes,
        defaultOutputModes=default_output_modes,
        skills=[Skill(**skill) for skill in skills]
    )
    
    return card

def get_agent_cards(
    handlers_config: Dict[str, Dict[str, Any]], 
    base_url: str
) -> Dict[str, AgentCard]:
    """
    Create agent cards for all handlers.
    
    Args:
        handlers_config: Dict of handler name to handler config
        base_url: Base URL for the server
        
    Returns:
        Dict of handler name to AgentCard
    """
    cards = {}
    
    for handler_name, handler_config in handlers_config.items():
        if handler_name in ("use_discovery", "handler_packages", "default"):
            continue
        
        try:
            card = create_agent_card(
                handler_name=handler_name,
                base_url=base_url,
                handler_config=handler_config
            )
            cards[handler_name] = card
            logger.debug(f"Created agent card for handler '{handler_name}'")
        except Exception as e:
            logger.error(f"Failed to create agent card for handler '{handler_name}': {e}")
    
    return cards