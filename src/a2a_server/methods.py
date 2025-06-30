# a2a_server/methods.py - Clean RPC methods with health check handling

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
            # Log request
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
            
            # Log result
            if method in ("tasks/send", "tasks/sendSubscribe") and isinstance(result, dict):
                task_id = result.get("id", "unknown")[:12]
                logger.info(f"✅ Task created: {task_id}...")
                
            return result

    return _decor

def register_methods(protocol: JSONRPCProtocol, manager: TaskManager) -> None:
    """Register all task-related RPC methods."""

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
        handler_name = raw.get('handler', 'default')
        
        # Check for duplicates first
        logger.info(f"🔍 RPC dedup check: session={p.session_id[:8]}, handler={handler_name}")
        
        existing_task_id = None
        try:
            existing_task_id = await deduplicator.check_duplicate(
                manager, p.session_id, p.message, handler_name
            )
        except Exception as e:
            logger.warning(f"⚠️ Deduplication check failed, continuing: {e}")
        
        if existing_task_id:
            logger.info(f"🔄 RPC reusing existing task: {existing_task_id}")
            try:
                existing_task = await manager.get_task(existing_task_id)
                return Task.model_validate(existing_task.model_dump()).model_dump(exclude_none=True, by_alias=True)
            except TaskNotFound:
                logger.warning(f"Duplicate task {existing_task_id} not found, creating new")
        
        # Create new task
        task = await manager.create_task(p.message, session_id=p.session_id, handler_name=handler_name)
        
        # Record for future deduplication
        try:
            await deduplicator.record_task(
                manager, p.session_id, p.message, handler_name, task.id
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to record task for deduplication: {e}")
        
        logger.info(f"✅ RPC new task created: {task.id}")
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @_rpc(protocol, "tasks/sendSubscribe", TaskSendParams.model_validate)
    async def _send_subscribe(method: str, p: TaskSendParams, raw: Dict[str, Any]):
        handler_name = raw.get("handler", "default")
        client_id = raw.get("id")
        
        # Check for duplicates first
        logger.info(f"🔍 Stream dedup check: session={p.session_id[:8]}, handler={handler_name}")
        
        existing_task_id = None
        try:
            existing_task_id = await deduplicator.check_duplicate(
                manager, p.session_id, p.message, handler_name
            )
        except Exception as e:
            logger.warning(f"⚠️ Stream deduplication check failed, continuing: {e}")
        
        if existing_task_id:
            logger.info(f"🔄 Stream reusing task: {existing_task_id}")
            try:
                task = await manager.get_task(existing_task_id)
                return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)
            except TaskNotFound:
                logger.warning(f"Stream task {existing_task_id} not found, creating new")
        
        # Create or reuse task
        try:
            task = await manager.create_task(p.message, session_id=p.session_id, handler_name=handler_name, task_id=client_id)
            
            # Record for future deduplication
            if client_id:
                try:
                    await deduplicator.record_task(
                        manager, p.session_id, p.message, handler_name, task.id
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Failed to record stream task for deduplication: {e}")
            
            logger.info(f"✅ Stream task created: {task.id}")
            
        except ValueError as exc:
            if "already exists" in str(exc).lower() and client_id:
                task = await manager.get_task(client_id)
                logger.info(f"🔄 Stream reusing existing: {task.id}")
            else:
                raise
                
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @_rpc(protocol, "tasks/resubscribe", lambda _: None)
    async def _resub(_: str, __, ___):
        return None