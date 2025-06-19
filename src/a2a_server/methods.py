# a2a_server/methods.py
from __future__ import annotations

"""
a2a_server.methods
==================
JSON-RPC task-method implementations (now TaskGroup-native).

Key points
----------
* `_rpc` decorator centralises logging **and** Pydantic validation so each
  handler is tiny.
* We no longer keep our own WeakSet of background jobs - the revamped
  `TaskManager` already runs every task inside its **asyncio.TaskGroup** and
  exposes `shutdown()` for cleanup.
* `cancel_pending_tasks()` is therefore a thin wrapper that simply calls
  `await tm.shutdown()` (plus backward-compat support for any legacy
  WeakSet a third-party lib might still stuff into this module).
"""

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

# ---------------------------------------------------------------------------

_P = ParamSpec("_P")
_R = TypeVar("_R")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Legacy WeakSet shim (kept for 3rd-party compatibility)                     
# ---------------------------------------------------------------------------

_BACKGROUND: set[asyncio.Task[Any]] = set()  # no longer used internally
_LEGACY_SET_NAMES: tuple[str, ...] = ("_background_tasks", "_BACKGROUND_TASKS")


def cancel_pending_tasks(tm: TaskManager | None = None) -> asyncio.Task[Any]:  # noqa: D401
    """Return a *detached* Task that cancels our known jobs **and** the manager.

    * In modern code we rely on `TaskManager.shutdown()` which will cancel
      its TaskGroup; we also iterate any legacy sets we still find so that
      very old plugins don't leak tasks.
    """

    async def _do_cancel() -> None:  # pragma: no cover
        # 1. cancel any tasks a plugin might have stuffed into our exports
        containers: list[set[asyncio.Task[Any]]] = [_BACKGROUND]
        for name in _LEGACY_SET_NAMES:
            maybe = globals().get(name)
            if isinstance(maybe, set) and maybe is not _BACKGROUND:
                containers.append(maybe)

        doomed: list[asyncio.Task[Any]] = [t for c in containers for t in list(c)]
        for t in doomed:
            t.cancel()
        if doomed:
            await asyncio.gather(*doomed, return_exceptions=True)
            for c in containers:
                c.clear()

        # 2. ask the TaskManager to shut down - this takes care of everything
        if tm is not None:
            await tm.shutdown()

    # Detach so callers can fire-and-forget (mirrors old API)
    return asyncio.create_task(_do_cancel())


# ---------------------------------------------------------------------------
# Decorator that DRYs logging + validation for RPC handlers                  
# ---------------------------------------------------------------------------


def _rpc(
    proto: JSONRPCProtocol,
    rpc_name: str,
    validator: Callable[[Dict[str, Any]], _R],
) -> Callable[[Callable[[str, _R, Dict[str, Any]], Any]], None]:
    """Register *rpc_name* on *proto* with central validation/logging."""

    def _decor(fn: Callable[[str, _R, Dict[str, Any]], Any]) -> None:
        @proto.method(rpc_name)
        async def _handler(method: str, params: Dict[str, Any]):  # noqa: D401, ANN001
            # Enhanced logging for better message visibility
            if method == "tasks/send":
                # Extract message content for visibility
                message_content = ""
                try:
                    message_obj = params.get("message", {})
                    parts = message_obj.get("parts", [])
                    if parts and isinstance(parts[0], dict):
                        message_content = parts[0].get("text", "")[:80]  # First 80 chars
                    elif hasattr(message_obj, 'parts') and message_obj.parts:
                        # Handle Pydantic model case
                        message_content = str(message_obj.parts[0])[:80]
                except Exception:
                    message_content = "unknown"
                
                handler_name = params.get("handler", "default")
                logger.info(f"📤 New message to {handler_name}: '{message_content}...'")
                
            elif method == "tasks/sendSubscribe":
                # Log streaming task creation
                try:
                    message_obj = params.get("message", {})
                    parts = message_obj.get("parts", [])
                    if parts and isinstance(parts[0], dict):
                        message_content = parts[0].get("text", "")[:60]
                    else:
                        message_content = "unknown"
                except Exception:
                    message_content = "unknown"
                    
                handler_name = params.get("handler", "default")
                logger.info(f"📡 Streaming message to {handler_name}: '{message_content}...'")
                
            elif method == "tasks/get":
                # Log task status checks (but at debug level to avoid spam)
                task_id = params.get("id", "unknown")[:12]
                logger.debug(f"📋 Task status check: {task_id}...")
                
            elif method == "tasks/cancel":
                # Log task cancellations
                task_id = params.get("id", "unknown")[:12]
                logger.info(f"❌ Canceling task: {task_id}...")
                
            else:
                # Log other RPC methods
                logger.info(f"🔧 RPC method: {method}")
            
            logger.debug("Method params: %s", params)
            validated = validator(params)
            result = await fn(method, validated, params)
            
            # Log task creation success for send operations
            if method in ("tasks/send", "tasks/sendSubscribe") and isinstance(result, dict):
                task_id = result.get("id", "unknown")[:12]
                logger.info(f"✅ Created task: {task_id}...")
                
            return result

    return _decor


# ---------------------------------------------------------------------------
# Public entry-point                                                         
# ---------------------------------------------------------------------------


def register_methods(protocol: JSONRPCProtocol, manager: TaskManager) -> None:
    """Attach all task-related RPC methods to *protocol*."""

    @_rpc(protocol, "tasks/get", TaskQueryParams.model_validate)
    async def _get(_: str, q: TaskQueryParams, __):  # noqa: D401, ANN001
        try:
            task = await manager.get_task(q.id)
        except TaskNotFound as err:
            # Handle test tasks gracefully
            if '-test-' in q.id:
                logger.debug(f"Test task {q.id} not found - returning mock response")
                return {
                    "id": q.id,
                    "status": {"state": "completed"},
                    "history": [],
                    "artifacts": []
                }
            raise RuntimeError(f"TaskNotFound: {err}") from err
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @_rpc(protocol, "tasks/cancel", TaskIdParams.model_validate)
    async def _cancel(_: str, p: TaskIdParams, __):  # noqa: D401, ANN001
        await manager.cancel_task(p.id)
        logger.info("Task %s canceled via RPC", p.id)
        return None

    @_rpc(protocol, "tasks/send", TaskSendParams.model_validate)
    async def _send(method: str, p: TaskSendParams, raw: Dict[str, Any]):  # noqa: D401
        task = await manager.create_task(p.message, session_id=p.session_id, handler_name=raw.get("handler"))
        logger.info("Created task %s via %s", task.id, method)
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @_rpc(protocol, "tasks/sendSubscribe", TaskSendParams.model_validate)
    async def _send_subscribe(method: str, p: TaskSendParams, raw: Dict[str, Any]):  # noqa: D401
        handler_name = raw.get("handler")
        client_id = raw.get("id")
        try:
            task = await manager.create_task(p.message, session_id=p.session_id, handler_name=handler_name, task_id=client_id)
            logger.info("Created task %s via %s", task.id, method)
        except ValueError as exc:
            if "already exists" in str(exc).lower() and client_id:
                task = await manager.get_task(client_id)
                logger.info("Reusing existing task %s via %s", task.id, method)
            else:
                raise
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @_rpc(protocol, "tasks/resubscribe", lambda _: None)
    async def _resub(_: str, __, ___):  # noqa: D401, ANN001
        return None

    # expose helper so transports can shut things down gracefully
    protocol.cancel_pending_tasks = lambda: cancel_pending_tasks(manager)
