# a2a_server/methods.py - Handle genuine duplicates from client bug

import asyncio
import logging
from typing import Any, Callable, Dict, ParamSpec, TypeVar

from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_json_rpc.spec import (
    Task,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
)
from a2a_server.tasks.task_manager import TaskManager, TaskNotFound

# Import the enhanced deduplicator with fixed timing
from a2a_server.deduplication import deduplicator

_P = ParamSpec("_P")
_R = TypeVar("_R")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _extract_message_preview(params: Dict[str, Any], max_len: int = 80) -> str:
    """Extract message preview for logging."""
    try:
        message = params.get("message", {})
        if isinstance(message, dict) and message.get("parts"):
            parts = message["parts"]
            if parts and isinstance(parts[0], dict):
                return parts[0].get("text", "")[:max_len]
        return str(message)[:max_len] if message else "empty"
    except Exception:
        return "unknown"

def _is_health_check_task(task_id: str) -> bool:
    """Check if this is a health check task that doesn't need to exist."""
    return task_id.endswith('-test-000') or task_id in ['ping-test-000', 'connection-test-000']

# ---------------------------------------------------------------------------
# RPC Method Registration
# ---------------------------------------------------------------------------

def _rpc(
    proto: JSONRPCProtocol,
    rpc_name: str,
    validator: Callable[[Dict[str, Any]], _R],
) -> Callable[[Callable[[str, _R, Dict[str, Any]], Any]], None]:
    """Register RPC method with logging."""

    def _decor(fn: Callable[[str, _R, Dict[str, Any]], Any]) -> None:
        @proto.method(rpc_name)
        async def _handler(method: str, params: Dict[str, Any]):
            # Log request with endpoint info
            if method == "tasks/send":
                message_preview = _extract_message_preview(params)
                handler_name = params.get("handler", "default")
                logger.info(f"📤 RPC to {handler_name}: '{message_preview}...'")
            elif method == "tasks/sendSubscribe":
                message_preview = _extract_message_preview(params, 60)
                handler_name = params.get("handler", "default")
                logger.info(f"📡 Stream to {handler_name}: '{message_preview}...'")
            
            # Process request
            validated = validator(params)
            result = await fn(method, validated, params)
            
            # Log result with duplicate detection info
            if method in ("tasks/send", "tasks/sendSubscribe") and isinstance(result, dict):
                task_id = result.get("id", "unknown")[:12]
                # Check if this was a reused task (genuine duplicate handling)
                if result.get("_was_duplicate", False):
                    logger.info(f"🔄 RPC returned existing task: {task_id}... (genuine duplicate from client)")
                else:
                    logger.info(f"✅ RPC task created: {task_id}...")
                
            return result

    return _decor

async def _handle_genuine_duplicate_request(
    manager: TaskManager,
    session_id: str,
    message,
    handler_name: str,
    endpoint_type: str,  # "rpc" or "stream"
    client_id: str = None
) -> Task:
    """
    Handle genuine duplicate requests from client bug.
    
    The client is sending the same message to both RPC and stream endpoints.
    We need to:
    1. Check if we already have a task for this exact request
    2. Return the existing task if found
    3. Create new task only if genuinely new
    4. Handle race conditions properly
    """
    
    # Step 1: Check for existing task via deduplication
    logger.debug(f"🔍 [{endpoint_type}] Checking for genuine duplicates")
    existing_task_id = await deduplicator.check_duplicate_before_task_creation(
        manager, session_id, message, handler_name
    )
    
    if existing_task_id:
        try:
            existing_task = await manager.get_task(existing_task_id)
            logger.info(f"🔄 [{endpoint_type}] Genuine duplicate detected - returning existing task: {existing_task_id}")
            
            # Mark this as a duplicate for logging
            task_dict = Task.model_validate(existing_task.model_dump()).model_dump(exclude_none=True, by_alias=True)
            task_dict["_was_duplicate"] = True
            return task_dict
            
        except TaskNotFound:
            logger.debug(f"⚠️ [{endpoint_type}] Duplicate task {existing_task_id} not found in manager, creating new")
    
    # Step 2: For stream requests with client_id, check if that specific task exists
    if endpoint_type == "stream" and client_id:
        try:
            existing_task = await manager.get_task(client_id)
            logger.info(f"🔄 [{endpoint_type}] Reusing existing stream task: {client_id}")
            
            task_dict = Task.model_validate(existing_task.model_dump()).model_dump(exclude_none=True, by_alias=True)
            task_dict["_was_duplicate"] = True
            return task_dict
            
        except TaskNotFound:
            pass  # Will create new task with this ID
    
    # Step 3: Create new task (no duplicates found)
    logger.debug(f"📝 [{endpoint_type}] Creating new task - no duplicates found")
    
    try:
        # For stream requests, use the client_id if provided
        task_id = client_id if endpoint_type == "stream" else None
        task = await manager.create_task(
            message, 
            session_id=session_id, 
            handler_name=handler_name, 
            task_id=task_id
        )
        
        # Step 4: Record for future duplicate detection
        logger.debug(f"💾 [{endpoint_type}] Recording task for deduplication: {task.id}")
        await deduplicator.record_task_after_creation(
            manager, session_id, message, handler_name, task.id
        )
        
        logger.debug(f"✅ [{endpoint_type}] New task created: {task.id}")
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)
        
    except ValueError as exc:
        if "already exists" in str(exc).lower() and client_id:
            # Race condition: task was created between our check and creation attempt
            logger.info(f"🏃 [{endpoint_type}] Race condition detected - task {client_id} created by another request")
            existing_task = await manager.get_task(client_id)
            
            task_dict = Task.model_validate(existing_task.model_dump()).model_dump(exclude_none=True, by_alias=True)
            task_dict["_was_duplicate"] = True
            return task_dict
        else:
            raise

def register_methods(protocol: JSONRPCProtocol, manager: TaskManager) -> None:
    """Register all task-related RPC methods with proper genuine duplicate handling."""

    @_rpc(protocol, "tasks/get", TaskQueryParams.model_validate)
    async def _get(_: str, q: TaskQueryParams, __):
        try:
            task = await manager.get_task(q.id)
        except TaskNotFound as err:
            # Handle health check tasks gracefully
            if _is_health_check_task(q.id):
                logger.debug(f"Health check task not found (expected): {q.id}")
                return {
                    "id": q.id,
                    "status": {"state": "completed"},
                    "session_id": "health-check",
                    "history": []
                }
            raise RuntimeError(f"TaskNotFound: {err}") from err
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @_rpc(protocol, "tasks/cancel", TaskIdParams.model_validate)
    async def _cancel(_: str, p: TaskIdParams, __):
        # Handle health check tasks gracefully
        if _is_health_check_task(p.id):
            logger.debug(f"Health check task cancel request (ignored): {p.id}")
            return None
            
        await manager.cancel_task(p.id)
        logger.info("Task %s canceled", p.id)
        return None

    @_rpc(protocol, "tasks/send", TaskSendParams.model_validate)
    async def _send(method: str, p: TaskSendParams, raw: Dict[str, Any]):
        """
        Handle RPC task creation with genuine duplicate detection.
        
        The client has a bug where it sends the same request to both
        tasks/send (RPC) and tasks/sendSubscribe (stream) endpoints.
        """
        handler_name = raw.get('handler', 'default')
        session_id = p.session_id or "default"
        
        return await _handle_genuine_duplicate_request(
            manager=manager,
            session_id=session_id,
            message=p.message,
            handler_name=handler_name,
            endpoint_type="rpc"
        )

    @_rpc(protocol, "tasks/sendSubscribe", TaskSendParams.model_validate)
    async def _send_subscribe(method: str, p: TaskSendParams, raw: Dict[str, Any]):
        """
        Handle stream task creation with genuine duplicate detection.
        
        This endpoint often receives the same request as tasks/send due to
        a client bug. We need to handle this gracefully.
        """
        handler_name = raw.get("handler", "default")
        client_id = raw.get("id")
        session_id = p.session_id or "default"
        
        return await _handle_genuine_duplicate_request(
            manager=manager,
            session_id=session_id,
            message=p.message,
            handler_name=handler_name,
            endpoint_type="stream",
            client_id=client_id
        )

    @_rpc(protocol, "tasks/resubscribe", lambda _: None)
    async def _resub(_: str, __, ___):
        return None

    # Add debug endpoint for monitoring genuine duplicates
    @protocol.method("debug/duplicate_stats")
    async def _debug_duplicate_stats(method: str, params: Dict[str, Any]):
        """Debug endpoint to monitor genuine duplicate handling."""
        stats = deduplicator.get_stats()
        task_manager_stats = manager.get_deduplication_stats()
        return {
            "deduplicator": stats,
            "task_manager": task_manager_stats,
            "method": method,
            "genuine_duplicate_handling": "enabled",
            "client_bug_mitigation": "active",
            "endpoints_affected": ["tasks/send", "tasks/sendSubscribe"]
        }