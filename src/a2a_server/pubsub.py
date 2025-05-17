# a2a_server/pubsub.py
import asyncio
from typing import Any, List

class EventBus:
    """Non-blocking publish/subscribe hub.

    *   **publish() never blocks**: slow subscribers are serviced in the
        background via `asyncio.create_task`, so the publisher continues
        immediately after local `put_nowait` attempts.
    *   Queues are unbounded for ordinary subscribers; tests can inject a
        bounded queue to emulate back-pressure.
    *   The same *event object* is pushed to every queue — consumers must treat
        it as read-only.
    """

    def __init__(self) -> None:  # noqa: D401 (not a public API docstring)
        self._queues: List[asyncio.Queue] = []

    # ---------------------------------------------------------------------
    # Subscription API
    # ---------------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        """Register and return a fresh **unbounded** queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove *q*; ignores if it's unknown (idempotent)."""
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    # ---------------------------------------------------------------------
    # Publish
    # ---------------------------------------------------------------------
    async def publish(self, event: Any) -> None:  # noqa: D401 (imperative)
        """Broadcast *event* to all subscribers without blocking the caller."""
        if not self._queues:
            return

        background: list[asyncio.Task] = []
        for q in list(self._queues):  # snapshot so unsubscribe during publish is safe
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Put in the background; fire-and-forget
                background.append(asyncio.create_task(q.put(event)))

        # Detach background tasks so "Task was destroyed but is pending!" doesn’t pop
        for t in background:
            t.add_done_callback(lambda _t: _t.exception())  # surfaces any errors

