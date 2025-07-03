# a2a_server/pubsub.py - Improved version with better error handling
import asyncio
import logging
from typing import Any, List

logger = logging.getLogger(__name__)

class EventBus:
    """Non-blocking publish/subscribe hub.

    *   **publish() never blocks**: slow subscribers are serviced in the
        background via `asyncio.create_task`, so the publisher continues
        immediately after local `put_nowait` attempts.
    *   **Error resilient**: broken queues don't stop delivery to other subscribers
    *   Queues are unbounded for ordinary subscribers; tests can inject a
        bounded queue to emulate back-pressure.
    *   The same *event object* is pushed to every queue — consumers must treat
        it as read-only.
    """

    def __init__(self) -> None:  # noqa: D401 (not a public API docstring)
        self._queues: List[asyncio.Queue] = []

    # ---------------------------------------------------------------------
    # Subscription API
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
        failed_queues: list[asyncio.Queue] = []
        
        for q in list(self._queues):  # snapshot so unsubscribe during publish is safe
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Put in the background; fire-and-forget
                background.append(asyncio.create_task(q.put(event)))
            except Exception as e:
                # Log error but continue with other queues
                logger.warning(f"Failed to deliver event to subscriber: {e}")
                failed_queues.append(q)
                
        # Detach background tasks so "Task was destroyed but is pending!" doesn't pop
        for t in background:
            t.add_done_callback(lambda _t: self._handle_background_task_result(_t))

    def _handle_background_task_result(self, task: asyncio.Task) -> None:
        """Handle background task completion and log any errors."""
        try:
            exception = task.exception()
            if exception:
                logger.warning(f"Background event delivery failed: {exception}")
        except Exception as e:
            # Exception getting the exception - shouldn't happen but be safe
            logger.error(f"Error handling background task result: {e}")