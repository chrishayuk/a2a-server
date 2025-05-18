#!/usr/bin/env python3
# a2a_server/routes/session_export.py
"""
Export and import routes for session data in the A2A server.

Provides endpoints for:
- Exporting session data to JSON
- Importing session data from JSON
"""

from fastapi import FastAPI, Request, HTTPException, Response, Body, Depends
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional, Any
import json
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

def register_session_export_routes(app: FastAPI) -> None:
    """Register routes for session export/import."""
    
    @app.get("/sessions/{session_id}/export", tags=["Sessions"], summary="Export a session")
    async def export_session(
        session_id: str,
        request: Request,
        handler_name: Optional[str] = None,
        include_token_usage: bool = True
    ):
        """
        Export a session to JSON.
        
        Returns a downloadable JSON file containing the session data including:
        - Conversation history
        - Token usage statistics (if include_token_usage=True)
        - Metadata about the session
        
        Args:
            session_id: The session ID to export
            handler_name: Optional handler name (uses default if not specified)
            include_token_usage: Whether to include token usage statistics (default: True)
        """
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
        
        # Check if the handler supports sessions
        if not hasattr(handler, "get_conversation_history") or not callable(getattr(handler, "get_conversation_history")):
            raise HTTPException(
                status_code=400, 
                detail=f"Handler {handler.name} does not support sessions"
            )
        
        try:
            # Get conversation history
            history = await handler.get_conversation_history(session_id)
            
            # Create export data
            export_data = {
                "session_id": session_id,
                "handler": handler.name,
                "conversation": history,
                "exported_at": datetime.now().isoformat()
            }
            
            # Add token usage if requested
            if include_token_usage and hasattr(handler, "get_token_usage"):
                try:
                    token_usage = await handler.get_token_usage(session_id)
                    export_data["token_usage"] = token_usage
                except Exception as e:
                    logger.error(f"Error getting token usage for session {session_id}: {e}")
            
            # Set filename for download
            filename = f"session_{session_id}_{handler.name}.json"
            
            # Return as downloadable file
            return Response(
                content=json.dumps(export_data, indent=2),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        except Exception as e:
            logger.error(f"Error exporting session: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/sessions/import", tags=["Sessions"], summary="Import a session")
    async def import_session(
        request: Request,
        session_data: Dict[str, Any] = Body(...),
        handler_name: Optional[str] = None
    ):
        """
        Import a session from JSON.
        
        Creates a new session using the conversation history from the provided JSON data.
        
        Args:
            session_data: The session data to import
            handler_name: Optional handler name (uses handler specified in session_data if not provided)
        
        Returns:
            Information about the newly created session
        """
        task_manager = request.app.state.task_manager
        
        # Validate the import data
        if "conversation" not in session_data:
            raise HTTPException(status_code=400, detail="Invalid session data: missing conversation")
        
        # Get the handler
        if handler_name:
            if handler_name not in task_manager.get_handlers():
                raise HTTPException(status_code=404, detail=f"Handler {handler_name} not found")
            handler = task_manager._handlers[handler_name]
        elif "handler" in session_data:
            handler_name = session_data["handler"]
            if handler_name not in task_manager.get_handlers():
                raise HTTPException(status_code=404, detail=f"Handler {handler_name} not found in import data")
            handler = task_manager._handlers[handler_name]
        else:
            default_name = task_manager.get_default_handler()
            if not default_name:
                raise HTTPException(status_code=404, detail="No default handler configured")
            handler = task_manager._handlers[default_name]
        
        # Check if the handler supports sessions
        if not hasattr(handler, "_get_agent_session_id") or not callable(getattr(handler, "_get_agent_session_id")):
            raise HTTPException(
                status_code=400, 
                detail=f"Handler {handler.name} does not support sessions"
            )
        
        try:
            # Create a new session
            new_session_id = str(uuid.uuid4())
            agent_session_id = handler._get_agent_session_id(new_session_id)
            if not agent_session_id:
                raise HTTPException(
                    status_code=500, 
                    detail="Failed to create new session"
                )
            
            # Import conversation messages
            conversation = session_data["conversation"]
            imported_count = 0
            
            for msg in conversation:
                # Extract role and content from the message
                role = msg.get("role", "")
                content = msg.get("content", "")
                
                if not content:
                    continue
                
                # Determine if the message is from the agent or user
                is_agent = role.lower() in ["assistant", "system", "ai", "agent"]
                
                # Add the message to the session
                success = await handler.add_to_session(agent_session_id, content, is_agent=is_agent)
                if success:
                    imported_count += 1
            
            if imported_count == 0:
                raise HTTPException(
                    status_code=400, 
                    detail="No messages were imported"
                )
            
            return {
                "status": "success",
                "message": f"Session imported successfully with ID: {new_session_id}",
                "new_session_id": new_session_id,
                "handler": handler.name,
                "message_count": imported_count
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error importing session: {e}")
            raise HTTPException(status_code=500, detail=str(e))