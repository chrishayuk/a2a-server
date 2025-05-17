# a2a_server/methods.py
"""
a2a_server.methods
==================
JSON-RPC task-method implementations.

Key points
----------
* One thin decorator - **`_rpc`** - centralises logging *and* Pydantic
  validation, so each handler is only a couple of lines long.
* Background asyncio jobs are tracked in a **WeakSet** to avoid leaks.
  The helper `cancel_pending_tasks()` cleanly cancels everything and can
  also shut down the associated `TaskManager`.
* Back-compat: old code and tests that still push tasks into
  `_background_tasks` / `_BACKGROUND_TASKS` (plain `set`s) are supported.
"""
from __future__ import annotations

import asyncio
import logging
import weakref
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

# ── background task tracking ───────────────────────────────────────────────
_BACKGROUND: weakref.WeakSet[asyncio.Task[Any]] = weakref.WeakSet()

# legacy names that external code (or very old tests) may still poke a set into
_LEGACY_SET_NAMES: tuple[str, ...] = ("_background_tasks", "_BACKGROUND_TASKS")


def _track(task: asyncio.Task[Any]) -> None:
    """Add *task* to the tracking set for later cancellation."""
    _BACKGROUND.add(task)


async def cancel_pending_tasks(tm: TaskManager | None = None) -> None:
    """
    Cancel **all** in-flight background tasks and optionally shut the
    passed-in *TaskManager* down.

    Handles both the modern WeakSet `_BACKGROUND` *and* any legacy plain
    sets that might exist in this module under historic names.
    """
    # 1. gather every container that might hold tasks
    containers: list[set[asyncio.Task[Any]]] = [_BACKGROUND]
    for name in _LEGACY_SET_NAMES:
        maybe = globals().get(name)
        if isinstance(maybe, (set, weakref.WeakSet)) and maybe is not _BACKGROUND:
            containers.append(maybe)

    # 2. flatten → cancel → await completion
    tasks_to_cancel: tuple[asyncio.Task[Any], ...] = tuple(
        t for c in containers for t in list(c)
    )
    if tasks_to_cancel:
        logger.info("Cancelling %d pending tasks", len(tasks_to_cancel))
        for t in tasks_to_cancel:
            t.cancel()
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        logger.debug("All background tasks cancelled")

    # 3. clear every container we touched
    for c in containers:
        c.clear()

    # 4. shut down the TaskManager if supplied
    if tm is not None:
        await tm.shutdown()


# ---------------------------------------------------------------------------
# Decorator that DRYs logging + validation for RPC handlers
# ---------------------------------------------------------------------------


def _rpc(
    proto: JSONRPCProtocol,
    rpc_name: str,
    validator: Callable[[Dict[str, Any]], _R],
) -> Callable[[Callable[[str, _R, Dict[str, Any]], Any]], None]:
    """
    Register *rpc_name* on *proto*.

    The wrapped function receives **three** arguments:
    `(method_name, validated_params, raw_params)` – so it can still access
    auxiliary fields (like `handler`, `id`, …) that aren’t part of the
    strict Pydantic model.
    """

    def _decor(fn: Callable[[str, _R, Dict[str, Any]], Any]) -> None:
        @proto.method(rpc_name)
        async def _handler(method: str, params: Dict[str, Any]):  # noqa: D401, ANN001
            logger.info("Received RPC method %s", method)
            logger.debug("Method params: %s", params)
            try:
                validated = validator(params)
            except Exception:  # pragma: no cover
                logger.exception("Parameter validation failed")
                raise
            return await fn(method, validated, params)

    return _decor


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def register_methods(protocol: JSONRPCProtocol, manager: TaskManager) -> None:
    """Attach all task-related RPC methods to *protocol*."""

    @_rpc(protocol, "tasks/get", TaskQueryParams.model_validate)
    async def _get(_: str, q: TaskQueryParams, __) -> Dict[str, Any]:
        try:
            task = await manager.get_task(q.id)
        except TaskNotFound as err:
            raise RuntimeError(f"TaskNotFound: {err}") from err

        return Task.model_validate(task.model_dump()).model_dump(
            exclude_none=True, by_alias=True
        )

    @_rpc(protocol, "tasks/cancel", TaskIdParams.model_validate)
    async def _cancel(_: str, p: TaskIdParams, __) -> None:
        await manager.cancel_task(p.id)
        logger.info("Task %s canceled via RPC", p.id)
        return None

    @_rpc(protocol, "tasks/send", TaskSendParams.model_validate)
    async def _send(method: str, p: TaskSendParams, raw: Dict[str, Any]) -> Dict[str, Any]:
        task = await manager.create_task(
            p.message,
            session_id=p.session_id,
            handler_name=raw.get("handler"),
        )
        logger.info("Created task %s via %s", task.id, method)
        return Task.model_validate(task.model_dump()).model_dump(
            exclude_none=True, by_alias=True
        )

    @_rpc(protocol, "tasks/sendSubscribe", TaskSendParams.model_validate)
    async def _send_subscribe(
        method: str,
        p: TaskSendParams,
        raw: Dict[str, Any],
    ) -> Dict[str, Any]:
        handler_name = raw.get("handler")
        client_id = raw.get("id")

        try:
            task = await manager.create_task(
                p.message,
                session_id=p.session_id,
                handler_name=handler_name,
                task_id=client_id,
            )
            logger.info("Created task %s via %s", task.id, method)
        except ValueError as exc:
            if "already exists" in str(exc).lower() and client_id:
                task = await manager.get_task(client_id)
                logger.info("Reusing existing task %s via %s", task.id, method)
            else:
                raise

        return Task.model_validate(task.model_dump()).model_dump(
            exclude_none=True, by_alias=True
        )

    @_rpc(protocol, "tasks/resubscribe", lambda _: None)
    async def _resub(_: str, __, ___) -> None:  # noqa: D401 – explicit no-op
        return None

    # expose helper so transports can shut things down gracefully
    protocol.cancel_pending_tasks = lambda: asyncio.create_task(
        cancel_pending_tasks(manager)
    )
