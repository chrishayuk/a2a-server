# a2a/server/methods.py
from a2a.models.spec import (
    TaskSendParams, TaskQueryParams, TaskIdParams,
    Task, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.task_manager import TaskManager
from a2a.server.pubsub import EventBus

def register_methods(
    protocol: JSONRPCProtocol,
    manager: TaskManager,
) -> None:
    @protocol.method("tasks/send")
    async def _send(method: str, params: dict) -> dict:
        p = TaskSendParams.model_validate(params)
        task = await manager.create_task(p.message, session_id=p.session_id)
        # Return using alias keys
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @protocol.method("tasks/get")
    async def _get(method: str, params: dict) -> dict:
        q = TaskQueryParams.model_validate(params)
        task = await manager.get_task(q.id)
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @protocol.method("tasks/cancel")
    async def _cancel(method: str, params: dict) -> None:
        iid = TaskIdParams.model_validate(params)
        await manager.cancel_task(iid.id)
        return None

    @protocol.method("tasks/sendSubscribe")
    async def _send_subscribe(method: str, params: dict) -> dict:
        p = TaskSendParams.model_validate(params)
        task = await manager.create_task(p.message, session_id=p.session_id)
        return Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)

    @protocol.method("tasks/resubscribe")
    async def _resubscribe(method: str, params: dict) -> None:
        return None
