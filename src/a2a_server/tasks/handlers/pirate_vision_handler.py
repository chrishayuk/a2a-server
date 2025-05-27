# a2a_server/tasks/handlers/pirate_vision_handler.py
from __future__ import annotations

"""
Pirate-Vision handler
~~~~~~~~~~~~~~~~~~~~~
Receives an image and responds with streaming pirate-speak text describing it.
Designed to demonstrate multimodal **continuous** updates (artifact streaming)
so front-ends can test incremental delivery.
"""

import asyncio
from typing import AsyncIterator, Optional

from a2a_json_rpc.spec import (
    Artifact,
    Message,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from a2a_server.tasks.task_handler import TaskHandler


class PirateVisionHandler(TaskHandler):
    """Accept an image, then stream back pirate commentary."""

    @property
    def name(self) -> str:  # noqa: D401
        return "pirate_vision"

    async def process_task(
        self,
        task_id: str,
        message: Message,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """Stream three short pirate‑speak lines then finish."""
        # ── working … ───────────────────────────────────────────────
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.working),
            final=False,
        )

        # pretend we are analysing the picture
        await asyncio.sleep(0.3)

        pirate_lines = [
            "Arrr, I spy a majestic beast o’ legend!",
            "Its mane be flowin’ like golden doubloons in the sun!",
            "A fine treasure fer any sailor’s eyes, aye!",
        ]

        # stream lines one by one
        for idx, line in enumerate(pirate_lines):
            artifact = Artifact(
                name="pirate_vision",
                index=idx,
                parts=[TextPart(type="text", text=line)],
            )
            yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
            await asyncio.sleep(0.2)

        # ── completed ───────────────────────────────────────────────
        yield TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.completed),
            final=True,
        )
