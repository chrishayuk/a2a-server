# File: a2a_server/agent_card.py
"""
Builds spec-compliant AgentCards.

* `url` → handler root  (…/chef_agent)
* No extra discovery fields here - `app.py` adds rpcEndpoint / eventsEndpoint
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
    cfg = handler_cfg.get("agent_card", {})

    # canonical URLs ----------------------------------------------------------
    handler_root = handler_root = cfg.get("url") or f"{base_url}/{handler_name}"
    # ------------------------------------------------------------------------

    # capabilities
    caps_cfg = cfg.get("capabilities", {})
    caps = AgentCapabilities(
        streaming=caps_cfg.get("streaming", True),
        pushNotifications=caps_cfg.get("pushNotifications", False),
        stateTransitionHistory=caps_cfg.get("stateTransitionHistory", False),
    )

    # default IO
    default_in  = cfg.get("defaultInputModes",  ["text/plain"])
    default_out = cfg.get("defaultOutputModes", ["text/plain"])

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

    # assemble card
    return SpecAgentCard(
        name=cfg.get("name", handler_name.replace("_", " ").title()),
        description=cfg.get("description", f"A2A handler for {handler_name}"),
        url=handler_root,                         # <── key fix
        version=cfg.get("version", "1.0.0"),
        documentationUrl=cfg.get("documentationUrl"),
        capabilities=caps,
        defaultInputModes=default_in,
        defaultOutputModes=default_out,
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
