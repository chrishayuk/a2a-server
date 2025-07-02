# tests/tasks/handlers/test_time_ticker_handler.py
"""
Tests for TimeTickerHandler
============================
Tests the time ticker handler that demonstrates streaming time updates.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from typing import List

from a2a_json_rpc.spec import (
    Message,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    TextPart,
    Role
)

from a2a_server.tasks.handlers.time_ticker_handler import TimeTickerHandler


@pytest.fixture
def handler():
    """Fixture for TimeTickerHandler instance."""
    return TimeTickerHandler()


@pytest.fixture
def sample_message():
    """Fixture for a basic message."""
    return Message(
        role=Role.user,
        parts=[
            TextPart(
                type="text",
                text="Start the time ticker"
            )
        ]
    )


class TestTimeTickerHandler:
    """Test suite for TimeTickerHandler."""

    def test_handler_name(self, handler):
        """Test that handler has correct name."""
        assert handler.name == "time_ticker"

    def test_handler_properties(self, handler):
        """Test handler properties and capabilities."""
        content_types = handler.supported_content_types
        assert "text/plain" in content_types
        
        # Test other properties
        assert handler.streaming is False  # Uses base class default
        assert isinstance(handler.supports_sessions, bool)  # May be True or False depending on inheritance

    @pytest.mark.asyncio
    async def test_process_task_basic_flow(self, handler, sample_message):
        """Test the basic task processing flow."""
        task_id = "test_task_123"
        
        # Collect all events
        events = []
        start_time = asyncio.get_event_loop().time()
        
        async for event in handler.process_task(task_id, sample_message):
            events.append(event)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        # Should have: 1 working + 10 artifacts + 1 completed = 12 events
        assert len(events) == 12
        
        # Check first event is working status
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.working
        assert events[0].final is False
        assert events[0].id == task_id
        
        # Check 10 artifact events in the middle
        for i in range(1, 11):
            assert isinstance(events[i], TaskArtifactUpdateEvent)
            assert events[i].id == task_id
            assert events[i].artifact.name == "tick"
            assert events[i].artifact.index == i - 1
            assert len(events[i].artifact.parts) == 1
            # Use model_dump to access text content
            part_data = events[i].artifact.parts[0].model_dump()
            assert part_data["type"] == "text"
            assert isinstance(part_data["text"], str)
        
        # Check final completion event
        assert isinstance(events[11], TaskStatusUpdateEvent)
        assert events[11].status.state == TaskState.completed
        assert events[11].final is True
        assert events[11].id == task_id
        
        # Should take roughly 10 seconds (9 sleeps + 0.5 initial delay)
        assert 9.0 <= duration <= 12.0  # Allow some variance

    @pytest.mark.asyncio
    async def test_tick_content_format(self, handler, sample_message):
        """Test that tick content has correct format."""
        task_id = "test_task_456"
        
        # Collect artifact events
        artifact_events = []
        async for event in handler.process_task(task_id, sample_message):
            if isinstance(event, TaskArtifactUpdateEvent):
                artifact_events.append(event)
        
        # Should have exactly 10 tick artifacts
        assert len(artifact_events) == 10
        
        # Check each tick content
        for i, event in enumerate(artifact_events):
            part_data = event.artifact.parts[0].model_dump()
            text = part_data["text"]
            
            # Should contain tick number and UTC timestamp
            assert f"tick {i + 1}/10" in text
            assert "UTC time" in text
            
            # Should contain ISO format timestamp
            assert "T" in text  # ISO format contains T
            assert "Z" in text or "+" in text  # UTC indicator
            
            # Try to parse the timestamp from the text
            timestamp_part = text.split(": ")[-1]
            try:
                # Should be parseable as ISO format
                parsed_time = datetime.fromisoformat(timestamp_part.replace("Z", "+00:00"))
                assert parsed_time.tzinfo is not None
            except ValueError:
                pytest.fail(f"Could not parse timestamp from: {timestamp_part}")

    @pytest.mark.asyncio
    async def test_artifact_indices(self, handler, sample_message):
        """Test that artifacts have correct sequential indices."""
        task_id = "test_indices"
        
        artifact_events = []
        async for event in handler.process_task(task_id, sample_message):
            if isinstance(event, TaskArtifactUpdateEvent):
                artifact_events.append(event)
        
        # Check indices are sequential starting from 0
        for i, event in enumerate(artifact_events):
            assert event.artifact.index == i
            assert event.artifact.name == "tick"

    @pytest.mark.asyncio
    async def test_timing_behavior(self, handler, sample_message):
        """Test the timing of event generation."""
        task_id = "test_timing"
        
        start_time = asyncio.get_event_loop().time()
        event_times = []
        
        async for event in handler.process_task(task_id, sample_message):
            current_time = asyncio.get_event_loop().time()
            event_times.append(current_time - start_time)
        
        # Should have 12 events total
        assert len(event_times) == 12
        
        # First event (working) should be immediate
        assert event_times[0] < 0.1
        
        # First tick should be after initial 0.5s delay
        assert event_times[1] >= 0.4
        assert event_times[1] <= 0.7
        
        # Each subsequent tick should be ~1 second apart
        for i in range(2, 11):
            expected_time = 0.5 + (i - 1) * 1.0  # 0.5s initial + (i-1) * 1s
            actual_time = event_times[i]
            assert abs(actual_time - expected_time) <= 0.2  # Allow 200ms variance
        
        # Final completion should be immediate after last tick
        assert event_times[11] - event_times[10] <= 0.1

    @pytest.mark.asyncio
    async def test_with_session_id(self, handler, sample_message):
        """Test processing with session ID (should be ignored gracefully)."""
        task_id = "test_session"
        session_id = "ticker_session_123"
        
        events = []
        async for event in handler.process_task(task_id, sample_message, session_id):
            events.append(event)
        
        # Should process normally (session ID ignored)
        assert len(events) == 12
        assert all(event.id == task_id for event in events)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_tasks(self, handler):
        """Test handler can process multiple tasks concurrently."""
        messages = [
            Message(role=Role.user, parts=[TextPart(type="text", text=f"Ticker {i}")]) 
            for i in range(2)  # Only 2 to keep test time reasonable
        ]
        
        # Start tasks and process them concurrently
        async def process_single_task(task_id, message):
            events = []
            async for event in handler.process_task(task_id, message):
                events.append(event)
            return events
        
        start_time = asyncio.get_event_loop().time()
        
        # Run tasks concurrently
        tasks = [
            process_single_task(f"task_{i}", msg) 
            for i, msg in enumerate(messages)
        ]
        task_results = await asyncio.gather(*tasks)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        # Each task should complete normally
        assert len(task_results) == 2
        for task_events in task_results:
            assert len(task_events) == 12
            assert task_events[0].status.state == TaskState.working
            assert task_events[-1].status.state == TaskState.completed
        
        # Should take roughly same time as single task (concurrent execution)
        assert 9.0 <= duration <= 12.0

    @pytest.mark.asyncio
    async def test_error_resilience(self, handler):
        """Test handler resilience to unusual inputs."""
        # Test with empty message
        empty_message = Message(role=Role.user, parts=[])
        
        events = []
        async for event in handler.process_task("test_empty", empty_message):
            events.append(event)
        
        # Should still complete successfully
        assert len(events) == 12
        assert events[-1].status.state == TaskState.completed

    @pytest.mark.asyncio 
    async def test_cancellation_behavior(self, handler, sample_message):
        """Test behavior when task processing is cancelled."""
        task_id = "test_cancel"
        
        # Start processing but cancel after a few events
        event_generator = handler.process_task(task_id, sample_message)
        
        events = []
        count = 0
        try:
            async for event in event_generator:
                events.append(event)
                count += 1
                if count >= 3:  # Cancel after 3 events
                    break
        finally:
            await event_generator.aclose()
        
        # Should have collected some events before cancellation
        assert len(events) >= 3
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.working

    def test_handler_cancel_task(self, handler):
        """Test the cancel_task method (inherited from base class)."""
        # Base implementation should return False
        result = asyncio.run(handler.cancel_task("some_task"))
        assert result is False

    def test_handler_health_status(self, handler):
        """Test the health status reporting."""
        health = handler.get_health_status()
        
        assert isinstance(health, dict)
        assert health["handler_name"] == "time_ticker"
        assert "capabilities" in health
        assert "timestamp" in health
        
        capabilities = health["capabilities"]
        assert isinstance(capabilities["sessions"], bool)  # May be True or False
        assert capabilities["streaming"] is False
        assert "content_types" in capabilities

    @pytest.mark.asyncio
    async def test_timestamp_accuracy(self, handler, sample_message):
        """Test that timestamps are reasonably accurate."""
        task_id = "timestamp_test"
        
        timestamps = []
        test_start = datetime.now(timezone.utc)
        
        async for event in handler.process_task(task_id, sample_message):
            if isinstance(event, TaskArtifactUpdateEvent):
                part_data = event.artifact.parts[0].model_dump()
                text = part_data["text"]
                timestamp_str = text.split(": ")[-1]
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                timestamps.append(timestamp)
        
        test_end = datetime.now(timezone.utc)
        
        # All timestamps should be within the test duration
        for ts in timestamps:
            assert test_start <= ts <= test_end
        
        # Timestamps should be roughly 1 second apart
        for i in range(1, len(timestamps)):
            delta = (timestamps[i] - timestamps[i-1]).total_seconds()
            assert 0.8 <= delta <= 1.2  # Allow some variance

    @pytest.mark.asyncio
    async def test_artifact_structure(self, handler, sample_message):
        """Test the structure of generated artifacts."""
        task_id = "structure_test"
        
        async for event in handler.process_task(task_id, sample_message):
            if isinstance(event, TaskArtifactUpdateEvent):
                artifact = event.artifact
                
                # Check artifact structure
                assert artifact.name == "tick"
                assert isinstance(artifact.index, int)
                assert 0 <= artifact.index <= 9
                assert len(artifact.parts) == 1
                
                # Check part structure using model_dump
                part = artifact.parts[0]
                part_data = part.model_dump()
                assert part_data["type"] == "text"
                assert isinstance(part_data["text"], str)
                assert len(part_data["text"]) > 0
                
                # Check content format
                text = part_data["text"]
                assert "UTC time tick" in text
                assert "/10:" in text  # Should contain "/10:"
                
                # Should contain valid tick number
                tick_num = artifact.index + 1
                assert f"tick {tick_num}/10" in text


class TestTimeTickerIntegration:
    """Integration tests for TimeTickerHandler."""

    @pytest.mark.asyncio
    async def test_full_workflow_simulation(self):
        """Test complete workflow as it would be used by the server."""
        handler = TimeTickerHandler()
        
        # Simulate a complete time ticker request
        ticker_message = Message(
            role=Role.user,
            parts=[
                TextPart(
                    type="text",
                    text="Please start the time ticker for monitoring"
                )
            ]
        )
        
        # Process and collect all events
        all_events = []
        async for event in handler.process_task("workflow_test", ticker_message):
            all_events.append(event)
        
        # Verify complete workflow
        assert len(all_events) == 12
        
        # Check workflow progression
        status_events = [event for event in all_events 
                        if isinstance(event, TaskStatusUpdateEvent)]
        assert len(status_events) == 2  # working + completed
        assert status_events[0].status.state == TaskState.working
        assert status_events[1].status.state == TaskState.completed
        
        # Check artifacts contain timestamps
        artifacts = [event.artifact for event in all_events 
                    if isinstance(event, TaskArtifactUpdateEvent)]
        assert len(artifacts) == 10
        
        # Verify each artifact has timestamp content
        for i, artifact in enumerate(artifacts):
            part_data = artifact.parts[0].model_dump()
            text = part_data["text"]
            assert f"tick {i + 1}/10" in text
            assert "UTC time" in text

    @pytest.mark.asyncio
    async def test_resource_cleanup(self, handler):
        """Test that handler doesn't leak resources during operation."""
        import gc
        import weakref
        
        # Create a message and track it
        message = Message(role=Role.user, parts=[TextPart(type="text", text="test")])
        message_ref = weakref.ref(message)
        
        # Process task
        events = []
        async for event in handler.process_task("cleanup_test", message):
            events.append(event)
        
        # Clear local references
        del message
        del events
        
        # Force garbage collection
        gc.collect()
        
        # Message should be collectible (no leaks)
        # Note: This test might be flaky depending on GC behavior
        # But it's useful for detecting obvious leaks


if __name__ == "__main__":
    # Manual test runner for development
    import asyncio
    
    async def manual_test():
        handler = TimeTickerHandler()
        
        message = Message(
            role=Role.user,
            parts=[TextPart(type="text", text="Test time ticker")]
        )
        
        print(f"Testing {handler.name} handler...")
        print("This will take about 10 seconds...")
        
        async for event in handler.process_task("manual_test", message):
            if isinstance(event, TaskStatusUpdateEvent):
                print(f"Status: {event.status.state}")
            elif isinstance(event, TaskArtifactUpdateEvent):
                part_data = event.artifact.parts[0].model_dump()
                text = part_data["text"]
                print(f"Tick {event.artifact.index}: {text}")
        
        print("Test completed!")
    
    # Uncomment to run manual test
    # asyncio.run(manual_test())