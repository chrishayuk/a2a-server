# File: tests/server/test_pubsub.py
import asyncio

import pytest

from a2a_server.pubsub import EventBus


@pytest.mark.asyncio
async def test_publish_to_all_subscribers():
    """Every active subscriber must receive the event once."""
    bus = EventBus()

    q1 = bus.subscribe()
    q2 = bus.subscribe()

    payload = {"msg": "hello"}
    await bus.publish(payload)

    assert await q1.get() is payload  # identity check - same object
    assert await q2.get() is payload


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    """After *unsubscribe*, the queue must not receive further events."""
    bus = EventBus()
    q = bus.subscribe()

    await bus.publish("one")
    assert await q.get() == "one"

    bus.unsubscribe(q)
    await bus.publish("two")

    # give event loop a tick
    await asyncio.sleep(0)
    assert q.empty()


@pytest.mark.asyncio
async def test_slow_consumer_does_not_block_others():
    """`publish` should resolve quickly even when a subscriber is back-pressured."""
    bus = EventBus()

    fast = bus.subscribe()

    # Slow consumer - bounded queue size 1 and pre-filled to force full state.
    slow: asyncio.Queue = asyncio.Queue(maxsize=1)
    await slow.put("prefill")
    bus._queues.append(slow)

    # `publish` must complete within timeout (fast-path) and deliver to fast queue.
    await asyncio.wait_for(bus.publish("ping"), timeout=0.05)
    assert await fast.get() == "ping"

    # Slow queue will eventually get the event; pull it to avoid leaks.
    await asyncio.wait_for(slow.get(), timeout=0.2)
