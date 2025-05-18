# File: a2a_server/routes/session_routes.py
from fastapi import FastAPI, Request, HTTPException, Query
from typing import Dict, List, Any, Optional
import logging

# Import session classes directly from the correct path
from a2a_server.tasks.handlers.adk.session_enabled_adk_handler import SessionAwareTaskHandler

logger = logging.getLogger(__name__)

def register_session_routes(app: FastAPI) -> None:
    """Register routes for session management."""
    
    @app.get("/sessions", tags=["Sessions"], summary="List active sessions")
    async def list_sessions(request: Request):
        """List all active sessions across handlers."""
        task_manager = request.app.state.task_manager
        session_store = request.app.state.session_store
        
        results = {}
        
        # Check each handler for session support
        handlers = task_manager.get_handlers()
        for handler_name in handlers:
            handler = task_manager._handlers[handler_name]
            if isinstance(handler, SessionAwareTaskHandler):
                # Get mapping of session IDs
                sessions = []
                for a2a_session_id, chuk_session_id in handler._session_map.items():
                    sessions.append({
                        "a2a_session_id": a2a_session_id,
                        "chuk_session_id": chuk_session_id,
                    })
                results[handler_name] = sessions
        
        return {
            "handlers_with_sessions": results,
            "total_sessions_in_store": len(await session_store.list_sessions())
        }
    
    @app.get("/sessions/{session_id}/history", tags=["Sessions"], summary="Get session history")
    async def get_session_history(
        session_id: str,
        request: Request,
        handler_name: Optional[str] = Query(None, description="Handler name (uses default if not specified)"),
    ):
        """Get conversation history for a session."""
        task_manager = request.app.state.task_manager
        
        # Get the handler
        if handler_name:
            if handler_name not in task_manager.get_handlers():
                raise HTTPException(status_code=404, detail=f"Handler {handler_name} not found")
            handler = task_manager._handlers[handler_name]
        else:
            default_name = task_manager.get_default_handler()
            if not default_name:
                raise HTTPException(status_code=404, detail="No default handler configured")
            handler = task_manager._handlers[default_name]
        
        # Check if it supports sessions
        if not isinstance(handler, SessionAwareTaskHandler):
            raise HTTPException(
                status_code=400, 
                detail=f"Handler {handler.name} does not support sessions"
            )
        
        # Get conversation history
        try:
            history = await handler.get_conversation_history(session_id)
            return {
                "session_id": session_id,
                "handler": handler.name,
                "messages": history
            }
        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/sessions/{session_id}/tokens", tags=["Sessions"], summary="Get token usage")
    async def get_session_tokens(
        session_id: str,
        request: Request,
        handler_name: Optional[str] = Query(None, description="Handler name (uses default if not specified)"),
    ):
        """Get token usage statistics for a session."""
        task_manager = request.app.state.task_manager
        
        # Get the handler
        if handler_name:
            if handler_name not in task_manager.get_handlers():
                raise HTTPException(status_code=404, detail=f"Handler {handler_name} not found")
            handler = task_manager._handlers[handler_name]
        else:
            default_name = task_manager.get_default_handler()
            if not default_name:
                raise HTTPException(status_code=404, detail="No default handler configured")
            handler = task_manager._handlers[default_name]
        
        # Check if it supports sessions
        if not isinstance(handler, SessionAwareTaskHandler):
            raise HTTPException(
                status_code=400, 
                detail=f"Handler {handler.name} does not support sessions"
            )
        
        # Get token usage
        try:
            token_usage = await handler.get_token_usage(session_id)
            return {
                "session_id": session_id,
                "handler": handler.name,
                "token_usage": token_usage
            }
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")
            raise HTTPException(status_code=500, detail=str(e))