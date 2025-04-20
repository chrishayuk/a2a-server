# a2a/server/methods.py
"""
JSON-RPC method implementations for the A2A server.
"""
import asyncio
import logging
from typing import Dict, Any

from a2a.json_rpc.spec import (
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
    Task,
)
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.tasks.task_manager import TaskManager, TaskNotFound

# Configure module logger
logger = logging.getLogger(__name__)

# Keep track of active background tasks
_background_tasks = set()


def _register_task(task):
    """Register a background task for cleanup."""
    _background_tasks.add(task)

    def _clean_task(t):
        _background_tasks.discard(t)
    task.add_done_callback(_clean_task)

    return task


async def cancel_pending_tasks():
    """Cancel all pending background tasks and wait for them to complete."""
    tasks = list(_background_tasks)
    num_tasks = len(tasks)

    if num_tasks > 0:
        logger.info(f"Cancelling {num_tasks} pending tasks")
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
            # Task not found → raise so JSON‑RPC wraps it
            raise Exception(f"TaskNotFound: {e}")

        logger.debug(f"Retrieved task {q.id}: state={task.status.state}")
        result = Task.model_validate(task.model_dump()).model_dump(
            exclude_none=True, by_alias=True
        )
        logger.debug(f"tasks/get returning: {result}")
        return result

    @protocol.method("tasks/cancel")
    async def _cancel(method: str, params: Dict[str, Any]) -> None:
        logger.info(f"Received RPC method {method}")
        logger.debug(f"Method params: {params}")
        iid = TaskIdParams.model_validate(params)
        await manager.cancel_task(iid.id)
        logger.info(f"Task {iid.id} canceled via RPC")
        return None

    @protocol.method("tasks/send")
    async def _send(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Received RPC method {method}")
        logger.debug(f"Method params: {params}")
        p = TaskSendParams.model_validate(params)

        handler_name = params.get("handler")
        client_task_id = params.get("id")

        # pass client_task_id via the correct keyword `task_id`
        task = await manager.create_task(
            p.message,
            session_id=p.session_id,
            handler_name=handler_name,
            task_id=client_task_id,
        )

        handler_info = f" using handler '{handler_name}'" if handler_name else ""
        logger.info(f"Created task {task.id} via {method}{handler_info}")

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
        client_task_id = params.get("id")

        # attempt to create new task, or reuse existing
        try:
            task = await manager.create_task(
                p.message,
                session_id=p.session_id,
                handler_name=handler_name,
                task_id=client_task_id,
            )
            logger.info(f"Created task {task.id} via {method}")
        except ValueError as e:
            # if task already exists, fetch it
            if "already exists" in str(e):
                task = await manager.get_task(client_task_id)
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
        # SSE transport handles replay; RPC method is a no-op
        logger.info(f"Received RPC method {method} (resubscribe)")
        logger.debug(f"Resubscribe params: {params}")
        return None

    # Attach the cleanup helper so the server can await any in‑flight calls
    protocol.cancel_pending_tasks = cancel_pending_tasks
