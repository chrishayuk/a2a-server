# a2a/server/pubsub.py
import asyncio
from typing import Any, List

class EventBus:
    """
    Simple in-memory publish/subscribe for task events.
    Subscribers receive all published events.
    """
    def __init__(self) -> None:
        self._queues: List[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def publish(self, event: Any) -> None:
        for q in list(self._queues):
            await q.put(event)