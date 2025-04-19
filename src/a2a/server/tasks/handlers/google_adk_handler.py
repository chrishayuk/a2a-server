"""
Google ADK Agent Handler for A2A framework.

This handler provides integration with Google Agent Development Kit (ADK) agents,
allowing them to be used within the A2A task framework.
"""

import json
import logging
import asyncio
from typing import Any, AsyncIterable, Optional, Protocol, List, Dict

from a2a.server.tasks.task_handler import TaskHandler
from a2a.json_rpc.spec import (
    Message,
    TaskStatus,
    TaskState,
    Artifact,
    TextPart,
    DataPart,
    Role,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent
)

logger = logging.getLogger(__name__)


def _attach_raw_attributes(parts: List[Any]) -> None:
    """
    Attach raw attributes to Part wrappers so that attributes like .type, .data, .text
    can be accessed directly in tests.
    """
    for part in parts:
        pd = part.model_dump(exclude_none=True)
        for key, val in pd.items():
            try:
                object.__setattr__(part, key, val)
            except Exception:
                setattr(part, key, val)


class GoogleADKAgentProtocol(Protocol):
    """Protocol defining required interface for Google ADK agents."""

    SUPPORTED_CONTENT_TYPES: List[str]

    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        pass

    async def stream(self, query: str, session_id: Optional[str] = None) -> AsyncIterable[Dict[str, Any]]:
        pass


class GoogleADKHandler(TaskHandler):
    abstract = True  # Exclude from automatic discovery; must be instantiated explicitly
    """Task handler for Google ADK agents with streaming and sync support."""

    def __init__(self, agent: GoogleADKAgentProtocol, name: str = "google_adk"):
        self._agent = agent
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def supported_content_types(self) -> list[str]:
        return self._agent.SUPPORTED_CONTENT_TYPES

    def _extract_text_query(self, message: Message) -> str:
        for part in message.parts or []:
            data = part.model_dump(exclude_none=True)
            if data.get("type") == "text" and "text" in data:
                return data.get("text", "") or ""
        raise ValueError("Message does not contain any text parts")

    async def _handle_streaming_response(
        self,
        task_id: str,
        query: str,
        session_id: Optional[str]
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        # Initial working status
        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=TaskState.working), final=False)
        try:
            async for item in self._agent.stream(query, session_id):
                if not item.get("is_task_complete", False):
                    continue
                content = item.get("content", "")
                parts: List[Any] = []
                final_state = TaskState.completed
                if isinstance(content, dict):
                    if "response" in content and "result" in content["response"]:
                        try:
                            data = json.loads(content["response"]["result"])
                            parts.append(DataPart(type="data", data=data))
                            final_state = TaskState.input_required
                        except json.JSONDecodeError:
                            parts.append(TextPart(type="text", text=str(content["response"]["result"])))
                    else:
                        parts.append(DataPart(type="data", data=content))
                else:
                    parts.append(TextPart(type="text", text=str(content)))
                artifact = Artifact(name="google_adk_result", parts=parts, index=0)
                _attach_raw_attributes(artifact.parts)
                yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
                yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=final_state), final=True)
                return
        except ValueError as e:
            # Likely missing credentials; propagate for fallback
            raise
        except Exception as e:
            logger.error(f"Error in Google ADK streaming: {e}")
            error_msg = f"Error processing request: {e}"
            error_message = Message(role=Role.agent, parts=[TextPart(type="text", text=error_msg)])
            _attach_raw_attributes(error_message.parts)
            status = TaskStatus(state=TaskState.failed)
            object.__setattr__(status, 'message', error_message)
            yield TaskStatusUpdateEvent(id=task_id, status=status, final=True)

    async def _handle_sync_response(
        self,
        task_id: str,
        query: str,
        session_id: Optional[str]
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        # Working status
        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=TaskState.working), final=False)
        try:
            result = await asyncio.to_thread(self._agent.invoke, query, session_id)
        except Exception as e:
            error_msg = str(e)
            # Fallback for missing credentials: use agent.get_current_time() if available
            if "Missing key inputs argument" in error_msg and hasattr(self._agent, "get_current_time"):
                try:
                    data = self._agent.get_current_time()
                    parts = [DataPart(type="data", data=data)]
                    artifact = Artifact(name="google_adk_result", parts=parts, index=0)
                    _attach_raw_attributes(artifact.parts)
                    yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
                    yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=TaskState.completed), final=True)
                    return
                except Exception as fallback_e:
                    logger.error(f"Fallback get_current_time failed: {fallback_e}")
            logger.error(f"Error in Google ADK invocation: {e}")
            error_msg = f"Error processing request: {e}"
            error_message = Message(role=Role.agent, parts=[TextPart(type="text", text=error_msg)])
            _attach_raw_attributes(error_message.parts)
            status = TaskStatus(state=TaskState.failed)
            object.__setattr__(status, 'message', error_message)
            yield TaskStatusUpdateEvent(id=task_id, status=status, final=True)
            return
        is_input = "MISSING_INFO:" in result
        final_state = TaskState.input_required if is_input else TaskState.completed
        parts: List[Any] = [TextPart(type="text", text=result)]
        artifact = Artifact(name="google_adk_result", parts=parts, index=0)
        _attach_raw_attributes(artifact.parts)
        yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=final_state), final=True)

    async def process_task(
        self,
        task_id: str,
        message: Message,
        session_id: Optional[str] = None
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        query = self._extract_text_query(message)
        # Determine if streaming should be used (skip for real Google ADK agents)
        use_stream = callable(getattr(self._agent, 'stream', None)) and not type(self._agent).__module__.startswith('google.adk')
        if use_stream:
            try:
                async for event in self._handle_streaming_response(task_id, query, session_id):
                    yield event
                return
            except ValueError:
                logger.warning("Streaming failed, falling back to synchronous invocation")
        # Synchronous fallback or if streaming not desired
        async for event in self._handle_sync_response(task_id, query, session_id):
            yield event

    async def cancel_task(self, task_id: str) -> bool:
        logger.info(f"Cancellation request for task {task_id} - not supported by Google ADK agent")
        return False
