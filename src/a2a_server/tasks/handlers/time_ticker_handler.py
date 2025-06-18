# a2a_server/tasks/handlers/time_ticker_handler.py
from __future__ import annotations

"""Time-Ticker handler
~~~~~~~~~~~~~~~~~~~~~~
Streams the current UTC time once per second for 10 seconds so
front-ends can verify continuous status / artifact updates.
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterable, Optional

from a2a_json_rpc.spec import (
    Artifact,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
    Message,
)

from a2a_server.tasks.handlers.task_handler import TaskHandler


class TimeTickerHandler(TaskHandler):
    """Simple demo handler that emits a time-stamp every second."""

    @property
    def name(self) -> str:  # noqa: D401
        return "time_ticker"

    async def process_task(
        self,
        task_id: str,
        message: Message,
        session_id: Optional[str] = None,
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        
        # ── initial state ───────────────────────────────────────────────
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False,
        )
        
        # Small delay to ensure SSE clients are connected
        await asyncio.sleep(0.5)

        # ── 10 ticks ────────────────────────────────────────────────────
        for idx in range(10):
            now = datetime.now(timezone.utc).isoformat()
            artifact = Artifact(
                name="tick",
                index=idx,
                parts=[TextPart(type="text", text=f"UTC time tick {idx + 1}/10: {now}")],
            )
            
            # Yield the artifact
            yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
            
            # Wait 1 second before next tick (except on last iteration)
            if idx < 9:
                await asyncio.sleep(1)

        # ── completed ───────────────────────────────────────────────────
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True,
        )