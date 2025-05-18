#!/usr/bin/env python3
# a2a_server/routes/session_analytics.py
"""
Analytics routes for session data in the A2A server.

Provides endpoints for:
- Overall session statistics
- Token usage analytics
- Model usage metrics
"""

from fastapi import FastAPI, Request, HTTPException, Query
from typing import Dict, Optional
import logging
from datetime import datetime

from a2a_server.session.lifecycle import SessionLifecycleManager

logger = logging.getLogger(__name__)

def register_session_analytics_routes(app: FastAPI) -> None:
    """Register routes for session analytics."""
    
    @app.get("/analytics/sessions", tags=["Analytics"], summary="Get session analytics")
    async def get_session_analytics(request: Request):
        """
        Get overall analytics about sessions.
        
        Returns session counts, token usage statistics, and model usage metrics.
        """
        # Check if lifecycle manager is available
        if not hasattr(request.app.state, "session_lifecycle_manager"):
            raise HTTPException(
                status_code=400, 
                detail="Session lifecycle manager not available"
            )
        
        lifecycle_manager = request.app.state.session_lifecycle_manager
        
        # Get basic session stats
        session_stats = await lifecycle_manager.get_session_stats()
        
        # Get token usage statistics
        token_usage = await _get_token_usage_stats(request)
        
        return {
            "session_stats": session_stats,
            "token_usage": token_usage,
            "timestamp": datetime.now().isoformat()
        }
    
    @app.get("/analytics/tokens", tags=["Analytics"], summary="Get token usage analytics")
    async def get_token_analytics(request: Request):
        """
        Get detailed token usage analytics.
        
        Returns token counts and costs broken down by model, handler, and time period.
        """
        token_usage = await _get_token_usage_stats(request)
        
        return {
            "token_usage": token_usage,
            "timestamp": datetime.now().isoformat()
        }

async def _get_token_usage_stats(request: Request) -> Dict:
    """
    Get token usage statistics across all session-enabled handlers.
    
    Returns:
        Dictionary containing token usage metrics
    """
    task_manager = request.app.state.task_manager
    
    token_usage = {
        "total_tokens": 0,
        "total_cost_usd": 0,
        "by_model": {},
        "by_handler": {}
    }
    
    # Get all handlers that support sessions
    for handler_name in task_manager.get_handlers():
        handler = task_manager._handlers.get(handler_name)
        
        # Check if handler supports sessions and has get_token_usage method
        if (hasattr(handler, "get_token_usage") and 
            callable(getattr(handler, "get_token_usage"))):
            
            handler_tokens = 0
            handler_cost = 0
            
            # Get session IDs from the handler
            session_ids = getattr(handler, "_session_map", {}).keys()
            
            # Aggregate token usage across all sessions for this handler
            for session_id in session_ids:
                try:
                    usage = await handler.get_token_usage(session_id)
                    
                    # Add to totals
                    total_tokens = usage.get("total_tokens", 0)
                    total_cost = usage.get("total_cost_usd", 0)
                    
                    token_usage["total_tokens"] += total_tokens
                    token_usage["total_cost_usd"] += total_cost
                    handler_tokens += total_tokens
                    handler_cost += total_cost
                    
                    # Add by model
                    for model, model_usage in usage.get("by_model", {}).items():
                        if model not in token_usage["by_model"]:
                            token_usage["by_model"][model] = {
                                "prompt_tokens": 0,
                                "completion_tokens": 0,
                                "total_tokens": 0,
                                "cost_usd": 0
                            }
                        
                        model_data = token_usage["by_model"][model]
                        model_data["prompt_tokens"] += model_usage.get("prompt_tokens", 0)
                        model_data["completion_tokens"] += model_usage.get("completion_tokens", 0)
                        model_data["total_tokens"] += model_usage.get("total_tokens", 0)
                        model_data["cost_usd"] += model_usage.get("cost_usd", 0)
                        
                except Exception as e:
                    logger.error(f"Error getting token usage for session {session_id}: {e}")
            
            # Add handler statistics
            token_usage["by_handler"][handler_name] = {
                "total_tokens": handler_tokens,
                "total_cost_usd": handler_cost,
                "session_count": len(session_ids)
            }
    
    return token_usage