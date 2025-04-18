# File: src/a2a/server/methods.py
import asyncio
import logging

from a2a.json_rpc.spec import (
    TaskSendParams,
    TaskQueryParams,
    TaskIdParams,
    Task,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    Artifact,
    TextPart,
    Part,
    Message,
    TaskState,
)
from a2a.json_rpc.protocol import JSONRPCProtocol
from a2a.server.task_manager import TaskManager

# Configure module logger
logger = logging.getLogger(__name__)


def register_methods(
    protocol: JSONRPCProtocol,
    manager: TaskManager,
) -> None:
    """
    Register JSON-RPC methods for task operations and a background runner to simulate processing,
    with detailed logging at each step.
    """
    # Background worker to simulate task processing
    async def _background_runner(task_id: str, initial_message: Message) -> None:
        logger.info(f"Background runner started for task {task_id}")
        try:
            # simulate processing delay
            await asyncio.sleep(1)
            logger.debug(f"Updating task {task_id} to working")
            await manager.update_status(task_id, TaskState.working)

            # extract text from the first part, handling generic Part objects
            text = ""
            if initial_message.parts:
                first_part = initial_message.parts[0]
                # if it's already a TextPart
                if isinstance(first_part, TextPart):
                    text = first_part.text or ""
                else:
                    # fallback: dump to dict and extract text key
                    part_data = first_part.model_dump(exclude_none=True)
                    text = part_data.get("text", "")
            logger.debug(f"Task {task_id} initial text: '{text}'")

            # produce an "echo" artifact
            echo_text = f"Echo: {text}"
            logger.debug(f"Adding artifact to task {task_id}: {echo_text}")
            echo_part = TextPart(type="text", text=echo_text)
            artifact = Artifact(name="echo", parts=[echo_part], index=0)
            await manager.add_artifact(task_id, artifact)

            # complete the task
            logger.debug(f"Updating task {task_id} to completed")
            await manager.update_status(task_id, TaskState.completed)
            logger.info(f"Background runner completed for task {task_id}")
        except Exception as e:
            logger.exception(f"Error in background runner for task {task_id}: {e}")

    @protocol.method("tasks/send")
    async def _send(method: str, params: dict) -> dict:
        logger.info(f"Received RPC method {method} with params: {params}")
        p = TaskSendParams.model_validate(params)
        task = await manager.create_task(p.message, session_id=p.session_id)
        logger.info(f"Task created {task.id}, scheduling background runner")
        # schedule background processing
        asyncio.create_task(_background_runner(task.id, p.message))
        # Return using alias keys
        result = Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)
        logger.debug(f"tasks/send returning: {result}")
        return result

    @protocol.method("tasks/get")
    async def _get(method: str, params: dict) -> dict:
        logger.info(f"Received RPC method {method} with params: {params}")
        q = TaskQueryParams.model_validate(params)
        task = await manager.get_task(q.id)
        result = Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)
        logger.debug(f"tasks/get returning: {result}")
        return result

    @protocol.method("tasks/cancel")
    async def _cancel(method: str, params: dict) -> None:
        logger.info(f"Received RPC method {method} with params: {params}")
        iid = TaskIdParams.model_validate(params)
        await manager.cancel_task(iid.id)
        logger.info(f"Task {iid.id} canceled via RPC")
        return None

    @protocol.method("tasks/sendSubscribe")
    async def _send_subscribe(method: str, params: dict) -> dict:
        logger.info(f"Received RPC method {method} with params: {params}")
        p = TaskSendParams.model_validate(params)
        task = await manager.create_task(p.message, session_id=p.session_id)
        logger.info(f"Task created {task.id} (sendSubscribe), scheduling background runner")
        asyncio.create_task(_background_runner(task.id, p.message))
        result = Task.model_validate(task.model_dump()).model_dump(exclude_none=True, by_alias=True)
        logger.debug(f"tasks/sendSubscribe returning: {result}")
        return result

    @protocol.method("tasks/resubscribe")
    async def _resubscribe(method: str, params: dict) -> None:
        # no-op: the SSE sidecar handles resubscribe by replaying events
        logger.info(f"Received RPC method {method} (resubscribe) with params: {params}")
        return None
