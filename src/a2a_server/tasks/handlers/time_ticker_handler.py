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

from a2a_server.tasks.task_handler import TaskHandler


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

        # ── 10 ticks ────────────────────────────────────────────────────
        for idx in range(10):
            now = datetime.now(timezone.utc).isoformat()
            artifact = Artifact(
                name="tick",
                index=idx,
                parts=[TextPart(type="text", text=f"UTC time: {now}")],
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
            await asyncio.sleep(1)

        # ── completed ───────────────────────────────────────────────────
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True,
        )