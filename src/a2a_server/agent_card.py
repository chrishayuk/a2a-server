# File: a2a_server/agent_card.py
"""
Builds spec-compliant AgentCards with proper URL handling.

* `url` → handler root  (…/chef_agent)
* Ensures proper URL resolution for different deployment scenarios
* Supports both direct handler access and agent card discovery
"""

import logging
from typing import Dict, Any, List
from urllib.parse import urljoin, urlparse

from a2a_json_rpc.spec import (
    AgentCard as SpecAgentCard,
    AgentCapabilities,
    AgentSkill,
    AgentProvider,
    AgentAuthentication,
)

logger = logging.getLogger(__name__)


def _normalize_base_url(base_url: str) -> str:
    """Normalize base URL to ensure proper formatting."""
    if not base_url:
        return "http://localhost:8000"
    
    # Ensure URL has protocol
    if not base_url.startswith(('http://', 'https://')):
        base_url = f"http://{base_url}"
    
    # Remove trailing slash for consistent joining
    return base_url.rstrip('/')


def _build_handler_url(base_url: str, handler_name: str, cfg: Dict[str, Any]) -> str:
    """Build the canonical handler URL."""
    normalized_base = _normalize_base_url(base_url)
    
    # Check if URL is explicitly configured
    explicit_url = cfg.get("agent_card", {}).get("url")
    if explicit_url:
        # If it's a relative URL, resolve against base
        if explicit_url.startswith('/'):
            return f"{normalized_base}{explicit_url}"
        elif not explicit_url.startswith(('http://', 'https://')):
            return f"{normalized_base}/{explicit_url}"
        else:
            return explicit_url
    
    # Default pattern: base_url/handler_name
    return f"{normalized_base}/{handler_name}"


def _build_documentation_url(handler_url: str, cfg: Dict[str, Any]) -> str:
    """Build documentation URL if not explicitly provided."""
    doc_url = cfg.get("agent_card", {}).get("documentationUrl") or cfg.get("agent_card", {}).get("documentation_url")
    if doc_url:
        return doc_url
    
    # Default: handler_url/docs
    return f"{handler_url}/docs"


def create_agent_card(
    handler_name: str,
    base_url: str,
    handler_cfg: Dict[str, Any],
) -> SpecAgentCard:
    """Create a spec-compliant agent card with proper URL handling."""
    cfg = handler_cfg.get("agent_card", {}) or {}  # Handle None case

    # Build canonical URLs
    handler_url = _build_handler_url(base_url, handler_name, handler_cfg)
    documentation_url = _build_documentation_url(handler_url, handler_cfg)

    # Capabilities - use both camelCase and snake_case for compatibility
    caps_cfg = cfg.get("capabilities", {})
    caps = AgentCapabilities(
        streaming=caps_cfg.get("streaming", True),
        push_notifications=caps_cfg.get("pushNotifications", caps_cfg.get("push_notifications", False)),
        state_transition_history=caps_cfg.get("stateTransitionHistory", caps_cfg.get("state_transition_history", False)),
        # Add other capabilities
        tools=caps_cfg.get("tools", handler_cfg.get("enable_tools", False)),
        sessions=caps_cfg.get("sessions", handler_cfg.get("enable_sessions", False)),
        vision=caps_cfg.get("vision", False),
    )

    # Default IO modes - check both field name formats
    default_in = cfg.get("defaultInputModes") or cfg.get("default_input_modes") or ["text/plain"]
    default_out = cfg.get("defaultOutputModes") or cfg.get("default_output_modes") or ["text/plain"]

    # Provider information
    provider_cfg = cfg.get("provider", {})
    provider = AgentProvider(
        organization=provider_cfg.get("organization", "A2A Server"),
        url=provider_cfg.get("url", base_url),
    ) if provider_cfg else None

    # Authentication schemes
    auth_cfg = cfg.get("authentication", {})
    authentication = AgentAuthentication(
        schemes=auth_cfg.get("schemes", ["None"])
    ) if auth_cfg else None

    # Skills with better defaults
    skills_cfg = cfg.get("skills")
    if not skills_cfg:
        # Create default skill based on handler configuration
        default_skill = {
            "id": f"{handler_name}-default",
            "name": cfg.get("name", handler_name.replace("_", " ").title()),
            "description": cfg.get("description", f"A2A handler for {handler_name}"),
            "tags": [handler_name, "a2a", "agent"],
        }
        
        # Add contextual examples if available
        if "examples" in cfg:
            default_skill["examples"] = cfg["examples"]
        
        skills_cfg = [default_skill]

    skills: List[AgentSkill] = []
    for skill_cfg in skills_cfg:
        try:
            skills.append(AgentSkill(**skill_cfg))
        except Exception as e:
            logger.warning(f"Failed to create skill for {handler_name}: {e}")
            # Continue with other skills

    # Assemble the agent card
    card_data = {
        "name": cfg.get("name", handler_name.replace("_", " ").title()),
        "description": cfg.get("description", f"A2A handler for {handler_name}"),
        "url": handler_url,
        "version": cfg.get("version", "1.0.0"),
        "capabilities": caps,
        "default_input_modes": default_in,
        "default_output_modes": default_out,
        "skills": skills,
    }
    
    # Add optional fields
    if documentation_url:
        card_data["documentation_url"] = documentation_url
    if provider:
        card_data["provider"] = provider
    if authentication:
        card_data["authentication"] = authentication

    return SpecAgentCard(**card_data)


def get_agent_cards(
    handlers_cfg: Dict[str, Dict[str, Any]], base_url: str
) -> Dict[str, SpecAgentCard]:
    """Generate agent cards for all configured handlers."""
    cards: Dict[str, SpecAgentCard] = {}
    
    for name, cfg in handlers_cfg.items():
        # Skip meta-configuration keys
        if name in ("use_discovery", "handler_packages", "default", "default_handler", "_session_store"):
            continue
        if not isinstance(cfg, dict):  # Skip non-dict values
            continue
            
        try:
            cards[name] = create_agent_card(name, base_url, cfg)
            logger.debug(f"Created agent card for {name}: {cards[name].url}")
        except Exception as exc:
            logger.error(f"Failed to create card for {name}: {exc}")
            
    return cards


def get_default_agent_card(
    handlers_cfg: Dict[str, Dict[str, Any]], 
    base_url: str
) -> SpecAgentCard | None:
    """Get the default agent card based on configuration."""
    default_handler = handlers_cfg.get("default_handler")
    cards = get_agent_cards(handlers_cfg, base_url)
    
    # Return the default handler's card if specified and available
    if default_handler and default_handler in cards:
        return cards[default_handler]
    
    # Return the first available card
    if cards:
        return next(iter(cards.values()))
    
    return None


def create_handler_specific_agent_card(
    handler_name: str,
    base_url: str,
    handler_cfg: Dict[str, Any],
    request_url: str = None
) -> SpecAgentCard:
    """
    Create an agent card for a specific handler with request context.
    
    This is useful for handler-specific endpoints like /handler_name/agent-card.json
    """
    # Use request URL base if available for more accurate URL generation
    if request_url:
        parsed = urlparse(request_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    return create_agent_card(handler_name, base_url, handler_cfg)


def validate_agent_card(card: SpecAgentCard) -> List[str]:
    """Validate an agent card and return list of issues."""
    issues = []
    
    if not card.name:
        issues.append("Missing required field: name")
    
    if not card.url:
        issues.append("Missing required field: url")
    
    if not card.skills:
        issues.append("No skills defined")
    
    # Validate URL format
    try:
        parsed = urlparse(card.url)
        if not parsed.scheme or not parsed.netloc:
            issues.append(f"Invalid URL format: {card.url}")
    except Exception:
        issues.append(f"Malformed URL: {card.url}")
    
    # Validate skills
    for i, skill in enumerate(card.skills):
        if not skill.id:
            issues.append(f"Skill {i} missing id")
        if not skill.name:
            issues.append(f"Skill {i} missing name")
    
    return issues