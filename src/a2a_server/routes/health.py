# File: a2a_server/routes/health.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# a2a imports
from a2a_server.agent_card import get_agent_cards

def register_health_routes(
    app: FastAPI,
    task_manager,
    handlers_config: dict
):
    @app.get("/", include_in_schema=False)
    async def _root_health(request: Request):
        base = str(request.base_url).rstrip("/")
        return {
            "status": "ok",
            "default_handler": task_manager.get_default_handler(),
            "handlers": task_manager.get_handlers(),
            "agent_card": f"{base}/.well-known/agent.json",
        }

    @app.get("/.well-known/agent.json", include_in_schema=False)
    async def _default_agent_card(request: Request):
        base = str(request.base_url).rstrip("/")
        default = task_manager.get_default_handler()
        if not default:
            return JSONResponse(status_code=404,
                                content={"error": "No default handler"})

        if not hasattr(app.state, "agent_cards"):
            app.state.agent_cards = get_agent_cards(handlers_config, base)

        card = app.state.agent_cards.get(default)
        if card:
            return card.dict(exclude_none=True)

        # fallback minimal card
        return {
            "name": default.replace("_", " ").title(),
            "description": f"A2A handler for {default}",
            "url": f"{base}",
            "version": "1.0.0",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [{
                "id": f"{default}-default",
                "name": default.replace("_", " ").title(),
                "description": f"Default capability for {default}",
                "tags": [default],
            }],
        }
