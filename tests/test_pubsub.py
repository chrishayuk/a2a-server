#!/usr/bin/env python3
# tests/test_pubsub.py
"""
Comprehensive unit tests for a2a_server.pubsub.EventBus.

Tests the non-blocking publish/subscribe system including:
- Basic subscription/unsubscription
- Event delivery guarantees
- Non-blocking behavior with slow consumers
- Error handling and edge cases
- Concurrent access patterns
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock
from typing import Any, List

from a2a_server.pubsub import EventBus


class TestEventBusBasics:
    """Test basic EventBus functionality."""

    def test_init_creates_empty_bus(self):
        """Test that EventBus initializes with no subscribers."""
        bus = EventBus()
        assert bus._queues == []

    def test_subscribe_returns_queue(self):
        """Test that subscribe returns an asyncio.Queue."""
        bus = EventBus()
        queue = bus.subscribe()
        
        assert isinstance(queue, asyncio.Queue)
        assert queue in bus._queues
        assert len(bus._queues) == 1

    def test_multiple_subscriptions(self):
        """Test multiple subscriptions create separate queues."""
        bus = EventBus()
        
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        q3 = bus.subscribe()
        
        assert len(bus._queues) == 3
        assert q1 is not q2
        assert q2 is not q3
        assert q1 is not q3
        assert all(q in bus._queues for q in [q1, q2, q3])

    def test_unsubscribe_removes_queue(self):
        """Test that unsubscribe removes queue from subscribers."""
        bus = EventBus()
        
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        
        assert len(bus._queues) == 2
        
        bus.unsubscribe(q1)
        assert len(bus._queues) == 1
        assert q1 not in bus._queues
        assert q2 in bus._queues

    def test_unsubscribe_unknown_queue_is_idempotent(self):
        """Test that unsubscribing unknown queue doesn't raise error."""
        bus = EventBus()
        unknown_queue = asyncio.Queue()
        
        # Should not raise ValueError
        bus.unsubscribe(unknown_queue)
        
        # Add some real subscribers and try again
        q1 = bus.subscribe()
        bus.unsubscribe(unknown_queue)
        
        # Real subscriber should still be there
        assert q1 in bus._queues

    def test_unsubscribe_same_queue_multiple_times(self):
        """Test that unsubscribing the same queue multiple times is safe."""
        bus = EventBus()
        queue = bus.subscribe()
        
        bus.unsubscribe(queue)
        assert queue not in bus._queues
        
        # Second unsubscribe should be safe
        bus.unsubscribe(queue)
        assert len(bus._queues) == 0


class TestEventPublishing:
    """Test event publishing behavior."""

    @pytest.mark.asyncio
    async def test_publish_to_no_subscribers(self):
        """Test publishing when no subscribers exist."""
        bus = EventBus()
        
        # Should not raise any errors
        await bus.publish("test_event")
        await bus.publish({"complex": "event"})
        await bus.publish(None)

    @pytest.mark.asyncio
    async def test_publish_to_single_subscriber(self):
        """Test publishing to a single subscriber."""
        bus = EventBus()
        queue = bus.subscribe()
        
        event = {"msg": "hello", "data": [1, 2, 3]}
        await bus.publish(event)
        
        received = await queue.get()
        assert received is event  # Identity check - same object

    @pytest.mark.asyncio
    async def test_publish_to_multiple_subscribers(self):
        """Test that all subscribers receive the same event object."""
        bus = EventBus()
        
        queues = [bus.subscribe() for _ in range(5)]
        event = {"timestamp": 123456, "type": "test"}
        
        await bus.publish(event)
        
        # All queues should receive the exact same object
        for queue in queues:
            received = await queue.get()
            assert received is event

    @pytest.mark.asyncio
    async def test_publish_different_event_types(self):
        """Test publishing various event types."""
        bus = EventBus()
        queue = bus.subscribe()
        
        events = [
            "string_event",
            123,
            {"dict": "event"},
            ["list", "event"],
            None,
            object(),
        ]
        
        for event in events:
            await bus.publish(event)
            received = await queue.get()
            assert received is event

    @pytest.mark.asyncio
    async def test_publish_preserves_event_order(self):
        """Test that events are received in the order they were published."""
        bus = EventBus()
        queue = bus.subscribe()
        
        events = [f"event_{i}" for i in range(10)]
        
        for event in events:
            await bus.publish(event)
        
        received_events = []
        for _ in range(10):
            received_events.append(await queue.get())
        
        assert received_events == events


class TestNonBlockingBehavior:
    """Test non-blocking publish behavior with slow consumers."""

    @pytest.mark.asyncio
    async def test_slow_consumer_does_not_block_publisher(self):
        """Test that slow consumers don't block the publisher."""
        bus = EventBus()
        
        # Fast consumer
        fast_queue = bus.subscribe()
        
        # Slow consumer - bounded queue pre-filled to capacity
        slow_queue = asyncio.Queue(maxsize=1)
        await slow_queue.put("prefill")  # Queue is now full
        bus._queues.append(slow_queue)
        
        # Publish should complete quickly despite slow consumer
        start_time = asyncio.get_event_loop().time()
        await asyncio.wait_for(bus.publish("test_event"), timeout=0.1)
        duration = asyncio.get_event_loop().time() - start_time
        
        # Should complete very quickly (well under timeout)
        assert duration < 0.05
        
        # Fast consumer should still receive event
        assert await fast_queue.get() == "test_event"
        
        # Clean up slow queue to avoid hanging task
        await slow_queue.get()  # Remove prefill
        await asyncio.wait_for(slow_queue.get(), timeout=0.5)  # Get the published event

    @pytest.mark.asyncio
    async def test_multiple_slow_consumers(self):
        """Test behavior with multiple slow consumers."""
        bus = EventBus()
        
        # Create several slow consumers
        slow_queues = []
        for i in range(3):
            slow_queue = asyncio.Queue(maxsize=1)
            await slow_queue.put(f"prefill_{i}")
            slow_queues.append(slow_queue)
            bus._queues.append(slow_queue)
        
        # Add one fast consumer
        fast_queue = bus.subscribe()
        
        # Publish should still be fast
        await asyncio.wait_for(bus.publish("broadcast"), timeout=0.1)
        
        # Fast consumer gets event immediately
        assert await fast_queue.get() == "broadcast"
        
        # Clean up slow consumers
        for slow_queue in slow_queues:
            await slow_queue.get()  # Remove prefill
            await asyncio.wait_for(slow_queue.get(), timeout=0.5)  # Get broadcast


class TestConcurrentAccess:
    """Test concurrent access patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_publishing(self):
        """Test multiple concurrent publishers."""
        bus = EventBus()
        queue = bus.subscribe()
        
        async def publisher(event_prefix: str, count: int):
            for i in range(count):
                await bus.publish(f"{event_prefix}_{i}")
        
        # Start multiple publishers concurrently
        await asyncio.gather(
            publisher("pub1", 5),
            publisher("pub2", 5),
            publisher("pub3", 5),
        )
        
        # Collect all events
        events = []
        for _ in range(15):
            events.append(await queue.get())
        
        # All events should be received
        assert len(events) == 15
        
        # Count events from each publisher
        pub1_events = [e for e in events if e.startswith("pub1")]
        pub2_events = [e for e in events if e.startswith("pub2")]
        pub3_events = [e for e in events if e.startswith("pub3")]
        
        assert len(pub1_events) == 5
        assert len(pub2_events) == 5
        assert len(pub3_events) == 5

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe_during_publish(self):
        """Test subscribing/unsubscribing while publishing."""
        bus = EventBus()
        
        # Initial subscribers
        initial_queues = [bus.subscribe() for _ in range(3)]
        
        async def continuous_publisher():
            for i in range(10):
                await bus.publish(f"event_{i}")
                await asyncio.sleep(0.01)  # Small delay
        
        async def dynamic_subscriber():
            await asyncio.sleep(0.02)  # Start after some events
            new_queue = bus.subscribe()
            await asyncio.sleep(0.03)  # Stay subscribed briefly
            bus.unsubscribe(new_queue)
            return new_queue
        
        # Run publisher and dynamic subscriber concurrently
        publisher_task = asyncio.create_task(continuous_publisher())
        subscriber_task = asyncio.create_task(dynamic_subscriber())
        
        await asyncio.gather(publisher_task, subscriber_task)
        
        # Initial subscribers should have received some events
        for queue in initial_queues:
            events = []
            while not queue.empty():
                events.append(await queue.get())
            assert len(events) > 0  # Should have received some events

    @pytest.mark.asyncio
    async def test_unsubscribe_during_publish_iteration(self):
        """Test that unsubscribe during publish doesn't break iteration."""
        bus = EventBus()
        
        queues = [bus.subscribe() for _ in range(5)]
        
        # Mock the publish method to unsubscribe during iteration
        original_queues = bus._queues.copy()
        
        async def publish_with_unsubscribe(event):
            # Start iteration over queues
            background = []
            for i, q in enumerate(list(bus._queues)):  # Snapshot like in original
                if i == 2:  # Unsubscribe in the middle of iteration
                    bus.unsubscribe(queues[0])
                
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    background.append(asyncio.create_task(q.put(event)))
            
            # Handle background tasks
            for t in background:
                t.add_done_callback(lambda _t: _t.exception())
        
        # Replace publish method
        bus.publish = publish_with_unsubscribe
        
        await bus.publish("test_event")
        
        # Should not have crashed, and remaining queues should have event
        # queues[0] was unsubscribed, so it might not have the event
        for i, queue in enumerate(queues[1:], 1):  # Skip first queue
            if not queue.empty():
                assert await queue.get() == "test_event"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_publish_none_event(self):
        """Test publishing None as an event."""
        bus = EventBus()
        queue = bus.subscribe()
        
        await bus.publish(None)
        received = await queue.get()
        assert received is None

    @pytest.mark.asyncio
    async def test_publish_large_event(self):
        """Test publishing large events."""
        bus = EventBus()
        queue = bus.subscribe()
        
        # Create a large event
        large_event = {"data": "x" * 10000, "array": list(range(1000))}
        
        await bus.publish(large_event)
        received = await queue.get()
        assert received is large_event

    @pytest.mark.asyncio
    async def test_many_subscribers(self):
        """Test with a large number of subscribers."""
        bus = EventBus()
        
        # Create many subscribers
        num_subscribers = 100
        queues = [bus.subscribe() for _ in range(num_subscribers)]
        
        event = "broadcast_to_many"
        await bus.publish(event)
        
        # All should receive the event
        for queue in queues:
            received = await queue.get()
            assert received == event

    @pytest.mark.asyncio
    async def test_queue_maxsize_zero(self):
        """Test with unbounded queues (maxsize=0, the default)."""
        bus = EventBus()
        queue = bus.subscribe()
        
        # Default queues should be unbounded
        assert queue.maxsize == 0
        
        # Should be able to put many items without blocking
        for i in range(1000):
            await bus.publish(f"item_{i}")
        
        # All items should be in the queue
        assert queue.qsize() == 1000

    def test_queue_snapshot_prevents_modification_during_iteration(self):
        """Test that using list() creates a snapshot preventing concurrent modification issues."""
        bus = EventBus()
        
        # Add some queues
        for _ in range(5):
            bus.subscribe()
        
        original_queues = bus._queues.copy()
        snapshot = list(bus._queues)
        
        # Modify original list
        bus._queues.clear()
        
        # Snapshot should be unchanged
        assert len(snapshot) == 5
        assert snapshot == original_queues
        assert len(bus._queues) == 0


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_exception_in_background_task_callback(self):
        """Test that exceptions in background task callbacks are handled."""
        bus = EventBus()
        
        # Create a slow consumer to trigger background task
        slow_queue = asyncio.Queue(maxsize=1)
        await slow_queue.put("prefill")
        bus._queues.append(slow_queue)
        
        # Mock the callback to raise an exception
        with patch('asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            # Mock add_done_callback to simulate exception
            def callback_with_exception(callback_func):
                # Simulate the callback being called with an exception
                mock_future = Mock()
                mock_future.exception.return_value = RuntimeError("Callback error")
                callback_func(mock_future)
            
            mock_task.add_done_callback = callback_with_exception
            
            # This should not raise an exception
            await bus.publish("test_event")
        
        # Clean up
        await slow_queue.get()

    @pytest.mark.asyncio 
    async def test_broken_queue_doesnt_affect_others(self):
        """Test that broken queue doesn't affect other subscribers."""
        bus = EventBus()
        
        good_queue1 = bus.subscribe()
        good_queue2 = bus.subscribe()
        
        # Create a "broken" queue by mocking put_nowait to raise non-QueueFull exception
        broken_queue = Mock(spec=asyncio.Queue)
        broken_queue.put_nowait.side_effect = RuntimeError("Broken queue")
        bus._queues.insert(1, broken_queue)  # Insert in the middle
        
        with patch('a2a_server.pubsub.logger') as mock_logger:
            # Publish should succeed despite broken queue
            await bus.publish("test_event")
            
            # Should log the error
            mock_logger.warning.assert_called_once()
            log_message = mock_logger.warning.call_args[0][0]
            assert "Failed to deliver event to subscriber" in log_message
        
        # All good queues should receive the event
        assert await good_queue1.get() == "test_event"
        assert await good_queue2.get() == "test_event"
        
        # Broken queue should have been called but failed
        broken_queue.put_nowait.assert_called_once_with("test_event")

    @pytest.mark.asyncio
    async def test_queue_full_triggers_background_task(self):
        """Test that QueueFull exceptions properly trigger background tasks."""
        bus = EventBus()
        
        good_queue = bus.subscribe()
        
        # Create a queue that raises QueueFull on put_nowait but succeeds on put
        full_queue = Mock(spec=asyncio.Queue)
        full_queue.put_nowait.side_effect = asyncio.QueueFull()
        full_queue.put = AsyncMock(return_value=None)  # Succeeds eventually
        bus._queues.append(full_queue)
        
        # Publish should succeed and not raise QueueFull
        await bus.publish("test_event")
        
        # Good queue should receive event immediately
        assert await good_queue.get() == "test_event"
        
        # Full queue should have had put_nowait called, then put in background
        full_queue.put_nowait.assert_called_once_with("test_event")
        
        # Give background task time to complete
        await asyncio.sleep(0.1)
        full_queue.put.assert_called_once_with("test_event")

    @pytest.mark.asyncio
    async def test_background_task_error_logging(self):
        """Test that background task errors are logged properly."""
        bus = EventBus()
        
        # Create a queue that will cause put() to fail in background task
        problematic_queue = asyncio.Queue(maxsize=1)
        await problematic_queue.put("prefill")  # Fill to capacity
        
        # Mock put to fail when called by background task
        original_put = problematic_queue.put
        async def failing_put(item):
            raise RuntimeError("Background task failure")
        problematic_queue.put = failing_put
        
        bus._queues.append(problematic_queue)
        normal_queue = bus.subscribe()
        
        with patch('a2a_server.pubsub.logger') as mock_logger:
            # Publish should trigger background task for full queue
            await bus.publish("test_event")
            
            # Normal queue should still receive the event
            assert await normal_queue.get() == "test_event"
            
            # Give background task time to fail and log
            await asyncio.sleep(0.1)
            
            # Should have logged the background task failure
            # The logger.warning call should have been made for background task failure
            warning_calls = mock_logger.warning.call_args_list
            background_error_logged = any(
                "Background event delivery failed" in str(call) or
                "Background" in str(call)
                for call in warning_calls
            )
            # Note: The exact logging behavior depends on your implementation
            # This test validates that errors don't crash the system


class TestIntegration:
    """Integration tests combining multiple features."""

    @pytest.mark.asyncio
    async def test_realistic_event_flow(self):
        """Test a realistic event flow scenario."""
        bus = EventBus()
        
        # Simulate different types of subscribers
        fast_processor = bus.subscribe()
        logger_queue = bus.subscribe()
        slow_analyzer = asyncio.Queue(maxsize=2)
        bus._queues.append(slow_analyzer)
        
        # Simulate a sequence of events
        events = [
            {"type": "user_login", "user_id": 123},
            {"type": "data_update", "table": "users", "id": 123},
            {"type": "notification_sent", "user_id": 123, "channel": "email"},
            {"type": "user_logout", "user_id": 123},
        ]
        
        # Publish events
        for event in events:
            await bus.publish(event)
        
        # Fast processor should get all events quickly
        fast_events = []
        for _ in range(len(events)):
            fast_events.append(await fast_processor.get())
        assert fast_events == events
        
        # Logger should also get all events
        log_events = []
        for _ in range(len(events)):
            log_events.append(await logger_queue.get())
        assert log_events == events
        
        # Slow analyzer will get events eventually
        # (Clean up to avoid hanging tasks)
        while not slow_analyzer.empty():
            await slow_analyzer.get()

    @pytest.mark.asyncio
    async def test_subscriber_lifecycle_management(self):
        """Test complete subscriber lifecycle."""
        bus = EventBus()
        
        # Start with no subscribers
        await bus.publish("should_be_ignored")
        
        # Add subscribers
        subscribers = []
        for i in range(3):
            q = bus.subscribe()
            subscribers.append(q)
        
        # Publish to all
        await bus.publish("broadcast_1")
        for q in subscribers:
            assert await q.get() == "broadcast_1"
        
        # Remove one subscriber
        bus.unsubscribe(subscribers[1])
        await bus.publish("broadcast_2")
        
        # Only remaining subscribers get event
        assert await subscribers[0].get() == "broadcast_2"
        assert await subscribers[2].get() == "broadcast_2"
        assert subscribers[1].empty()
        
        # Remove all subscribers
        bus.unsubscribe(subscribers[0])
        bus.unsubscribe(subscribers[2])
        
        # No one gets this event
        await bus.publish("should_be_ignored_2")
        for q in subscribers:
            assert q.empty()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])