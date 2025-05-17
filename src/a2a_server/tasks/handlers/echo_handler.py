# a2a_server/tasks/handlers/echo_handler.py
import asyncio

# a2a imports
from a2a_server.tasks.task_handler import TaskHandler
from a2a_json_rpc.spec import (
    Message, TaskStatus, TaskState, Artifact, TextPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent
)

class EchoHandler(TaskHandler):
    @property
    def name(self) -> str:
        return "echo"
    
    async def process_task(self, task_id, message, session_id=None):
        # First yield a "working" status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False
        )
        
        await asyncio.sleep(1)  # simulate work
        
        # Extract text from first part
        text = ""
        if message.parts:
            first_part = message.parts[0]
            part_data = first_part.model_dump(exclude_none=True)
            if "text" in part_data:
                text = part_data["text"] or ""
        
        # Create and yield an artifact
        echo_text = f"Echo: {text}"
        echo_part = TextPart(type="text", text=echo_text)
        artifact = Artifact(name="echo", parts=[echo_part], index=0)
        
        yield TaskArtifactUpdateEvent(
            id=task_id,
            artifact=artifact
        )
        
        # Finally, yield completion status
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True
        )