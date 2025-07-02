# File: a2a_server/agent_card.py
"""
Builds spec-compliant AgentCards.

* `url` → handler root  (…/chef_agent)
* No extra discovery fields here - `app.py` adds rpcEndpoint / eventsEndpoint
"""

import logging
from typing import Dict, Any, List

from a2a_json_rpc.spec import (
    AgentCard as SpecAgentCard,
    AgentCapabilities,
    AgentSkill,
)

logger = logging.getLogger(__name__)


def create_agent_card(
    handler_name: str,
    base_url: str,
    handler_cfg: Dict[str, Any],
) -> SpecAgentCard:
    cfg = handler_cfg.get("agent_card", {}) or {}  # Handle None case

    # canonical URLs ----------------------------------------------------------
    handler_root = cfg.get("url") or f"{base_url}/{handler_name}"
    # ------------------------------------------------------------------------

    # capabilities - use both camelCase and snake_case for compatibility
    caps_cfg = cfg.get("capabilities", {})
    caps = AgentCapabilities(
        streaming=caps_cfg.get("streaming", True),
        push_notifications=caps_cfg.get("pushNotifications", caps_cfg.get("push_notifications", False)),
        state_transition_history=caps_cfg.get("stateTransitionHistory", caps_cfg.get("state_transition_history", False)),
    )

    # default IO - check both field name formats
    default_in = cfg.get("defaultInputModes") or cfg.get("default_input_modes") or ["text/plain"]
    default_out = cfg.get("defaultOutputModes") or cfg.get("default_output_modes") or ["text/plain"]

    # skills
    skills_cfg = cfg.get("skills") or [{
        "id": f"{handler_name}-default",
        "name": cfg.get("name", handler_name.replace("_", " ").title()),
        "description": cfg.get(
            "description", f"A2A handler for {handler_name}"
        ),
        "tags": [handler_name],
    }]
    skills: List[AgentSkill] = [AgentSkill(**s) for s in skills_cfg]

    # assemble card - check both field name formats
    return SpecAgentCard(
        name=cfg.get("name", handler_name.replace("_", " ").title()),
        description=cfg.get("description", f"A2A handler for {handler_name}"),
        url=handler_root,
        version=cfg.get("version", "1.0.0"),
        documentation_url=cfg.get("documentationUrl") or cfg.get("documentation_url"),
        capabilities=caps,
        default_input_modes=default_in,
        default_output_modes=default_out,
        skills=skills,
    )


def get_agent_cards(
    handlers_cfg: Dict[str, Dict[str, Any]], base_url: str
) -> Dict[str, SpecAgentCard]:
    cards: Dict[str, SpecAgentCard] = {}
    for name, cfg in handlers_cfg.items():
        if name in ("use_discovery", "handler_packages", "default", "default_handler"):
            continue
        if not isinstance(cfg, dict):  # ✅ skip strings
            continue
        try:
            cards[name] = create_agent_card(name, base_url, cfg)
            logger.debug("Created agent card for %s", name)
        except Exception as exc:
            logger.error("Failed to create card for %s: %s", name, exc)
    return cards