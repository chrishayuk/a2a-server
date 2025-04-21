# a2a_server/methods.py

"""
JSON-RPC method implementations for the A2A server.
"""
import asyncio
import logging
from typing import Any, Dict, Set

from a2a_json_rpc.spec import (
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
    Task,
)
from a2a_json_rpc.protocol import JSONRPCProtocol
from a2a_server.tasks.task_manager import TaskManager, TaskNotFound

# Configure module logger
logger = logging.getLogger(__name__)

# Keep track of active background tasks
_background_tasks: Set[asyncio.Task[Any]] = set()


def _register_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    """Register a background task for cleanup."""
    _background_tasks.add(task)

    def _clean_task(t: asyncio.Task[Any]) -> None:
        _background_tasks.discard(t)

    task.add_done_callback(_clean_task)
    return task


async def cancel_pending_tasks() -> None:
    """Cancel all pending background tasks and wait for them to complete."""
    tasks = list(_background_tasks)
    if tasks:
        logger.info(f"Cancelling {len(tasks)} pending tasks")
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.debug("All tasks cancelled successfully")
        _background_tasks.clear()


def register_methods(
    protocol: JSONRPCProtocol,
    manager: TaskManager,
) -> None:
    """
    Register JSON-RPC methods for task operations.
    """

    @protocol.method("tasks/get")
    async def _get(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Received RPC method {method}")
        logger.debug(f"Method params: {params}")

        q = TaskQueryParams.model_validate(params)
        try:
            task = await manager.get_task(q.id)
        except TaskNotFound as e:
            raise Exception(f"TaskNotFound: {e}")

        result = Task.model_validate(task.model_dump()).model_dump(
            exclude_none=True, by_alias=True
        )
        logger.debug(f"tasks/get returning: {result}")
        return result

    @protocol.method("tasks/cancel")
    async def _cancel(method: str, params: Dict[str, Any]) -> None:
        logger.info(f"Received RPC method {method}")
        logger.debug(f"Method params: {params}")

        p = TaskIdParams.model_validate(params)
        await manager.cancel_task(p.id)
        logger.info(f"Task {p.id} canceled via RPC")
        return None

    @protocol.method("tasks/send")
    async def _send(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Received RPC method {method}")
        logger.debug(f"Method params: {params}")

        # Validate against spec
        p = TaskSendParams.model_validate(params)

        # Pick optionally specified handler
        handler_name = params.get("handler")

        # Always generate a fresh task id per send (ignore client id)
        task = await manager.create_task(
            p.message,
            session_id=p.session_id,
            handler_name=handler_name,
        )

        info = f" using handler '{handler_name}'" if handler_name else ""
        logger.info(f"Created task {task.id} via {method}{info}")

        result = Task.model_validate(task.model_dump()).model_dump(
            exclude_none=True, by_alias=True
        )
        logger.debug(f"tasks/send returning: {result}")
        return result

    @protocol.method("tasks/sendSubscribe")
    async def _send_subscribe(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Received RPC method {method}")
        logger.debug(f"Method params: {params}")

        p = TaskSendParams.model_validate(params)
        handler_name = params.get("handler")
        client_id = params.get("id")

        try:
            # first‐time: create
            task = await manager.create_task(
                p.message,
                session_id=p.session_id,
                handler_name=handler_name,
                task_id=client_id,
            )
            logger.info(f"Created task {task.id} via {method}")
        except ValueError as e:
            if "already exists" in str(e).lower():
                task = await manager.get_task(client_id)
                logger.info(f"Reusing existing task {task.id} via {method}")
            else:
                raise

        result = Task.model_validate(task.model_dump()).model_dump(
            exclude_none=True, by_alias=True
        )
        logger.debug(f"tasks/sendSubscribe returning: {result}")
        return result

    @protocol.method("tasks/resubscribe")
    async def _resubscribe(method: str, params: Dict[str, Any]) -> None:
        logger.info(f"Received RPC method {method} (resubscribe)")
        logger.debug(f"Resubscribe params: {params}")
        # No-op: SSE transport replays past events
        return None

    # Allow callers to cancel any in-flight RPC calls
    protocol.cancel_pending_tasks = cancel_pending_tasks
