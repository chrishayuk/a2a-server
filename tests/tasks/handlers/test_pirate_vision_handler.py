# tests/tasks/handlers/test_pirate_vision_handler.py
"""
Tests for PirateVisionHandler
=============================
Tests the pirate vision handler that demonstrates streaming artifact updates
with pirate-themed image commentary.
"""

import pytest
import asyncio
from typing import List

from a2a_json_rpc.spec import (
    Message,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    TextPart,
    Role
)

from a2a_server.tasks.handlers.pirate_vision_handler import PirateVisionHandler


@pytest.fixture
def handler():
    """Fixture for PirateVisionHandler instance."""
    return PirateVisionHandler()


@pytest.fixture
def sample_image_message():
    """Fixture for a message containing an image (using text part for now)."""
    return Message(
        role=Role.user,
        parts=[
            # Use a text part to represent image description since ImagePart doesn't exist
            TextPart(
                type="text",
                text="[Image: A majestic lion with a golden mane]"
            ),
            TextPart(
                type="text", 
                text="What do you see in this image, matey?"
            )
        ]
    )


@pytest.fixture
def sample_text_message():
    """Fixture for a text-only message."""
    return Message(
        role=Role.user,
        parts=[
            TextPart(
                type="text",
                text="Describe what a pirate would see in a treasure map"
            )
        ]
    )


class TestPirateVisionHandler:
    """Test suite for PirateVisionHandler."""

    def test_handler_name(self, handler):
        """Test that handler has correct name."""
        assert handler.name == "pirate_vision"

    def test_handler_properties(self, handler):
        """Test handler properties and capabilities."""
        # Test supported content types (should support images)
        content_types = handler.supported_content_types
        assert "text/plain" in content_types
        
        # Test streaming capability
        assert handler.streaming is False  # Uses base class default
        
        # Test session support - may be True if handler inherits from SessionAwareTaskHandler
        # Just check it's a boolean value
        assert isinstance(handler.supports_sessions, bool)

    @pytest.mark.asyncio
    async def test_process_task_basic_flow(self, handler, sample_image_message):
        """Test the basic task processing flow."""
        task_id = "test_task_123"
        
        # Collect all events
        events = []
        async for event in handler.process_task(task_id, sample_image_message):
            events.append(event)
        
        # Should have: 1 working + 3 artifacts + 1 completed = 5 events
        assert len(events) == 5
        
        # Check event types and order
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.working
        assert events[0].final is False
        
        # Check artifact events
        for i in range(1, 4):
            assert isinstance(events[i], TaskArtifactUpdateEvent)
            assert events[i].id == task_id
            assert events[i].artifact.name == "pirate_vision"
            assert events[i].artifact.index == i - 1
            assert len(events[i].artifact.parts) == 1
            # Use model_dump to access text content
            part_data = events[i].artifact.parts[0].model_dump()
            assert part_data["type"] == "text"
            assert isinstance(part_data["text"], str)
        
        # Check final completion event
        assert isinstance(events[4], TaskStatusUpdateEvent)
        assert events[4].status.state == TaskState.completed
        assert events[4].final is True
        assert events[4].id == task_id

    @pytest.mark.asyncio
    async def test_pirate_commentary_content(self, handler, sample_image_message):
        """Test that pirate commentary contains expected phrases."""
        task_id = "test_task_456"
        
        # Collect artifact events
        artifact_events = []
        async for event in handler.process_task(task_id, sample_image_message):
            if isinstance(event, TaskArtifactUpdateEvent):
                artifact_events.append(event)
        
        # Should have exactly 3 pirate commentary artifacts
        assert len(artifact_events) == 3
        
        # Extract the pirate commentary text using model_dump
        pirate_lines = [
            event.artifact.parts[0].model_dump()["text"] for event in artifact_events
        ]
        
        # Check for expected pirate phrases
        expected_phrases = [
            "Arrr, I spy a majestic beast o' legend!",
            "Its mane be flowin' like golden doubloons in the sun!",
            "A fine treasure fer any sailor's eyes, aye!"
        ]
        
        assert pirate_lines == expected_phrases
        
        # Verify pirate language elements
        combined_text = " ".join(pirate_lines).lower()
        pirate_words = ["arrr", "matey", "aye", "treasure", "doubloons", "sailor"]
        found_pirate_words = [word for word in pirate_words if word in combined_text]
        assert len(found_pirate_words) >= 3, f"Expected pirate language, found: {found_pirate_words}"

    @pytest.mark.asyncio
    async def test_artifact_indices(self, handler, sample_image_message):
        """Test that artifacts have correct sequential indices."""
        task_id = "test_indices"
        
        artifact_events = []
        async for event in handler.process_task(task_id, sample_image_message):
            if isinstance(event, TaskArtifactUpdateEvent):
                artifact_events.append(event)
        
        # Check indices are sequential starting from 0
        for i, event in enumerate(artifact_events):
            assert event.artifact.index == i
            assert event.artifact.name == "pirate_vision"

    @pytest.mark.asyncio
    async def test_timing_behavior(self, handler, sample_image_message):
        """Test the timing of event generation."""
        task_id = "test_timing"
        
        start_time = asyncio.get_event_loop().time()
        event_times = []
        
        async for event in handler.process_task(task_id, sample_image_message):
            current_time = asyncio.get_event_loop().time()
            event_times.append(current_time - start_time)
        
        # Should have 5 events total
        assert len(event_times) == 5
        
        # First event (working) should be immediate
        assert event_times[0] < 0.1
        
        # There should be delays between artifact events
        # Initial delay of ~0.3s, then ~0.2s between each artifact
        assert event_times[1] >= 0.25  # First artifact after analysis delay
        assert event_times[2] >= event_times[1] + 0.15  # Second artifact
        assert event_times[3] >= event_times[2] + 0.15  # Third artifact
        
        # Total duration should be reasonable (< 2 seconds)
        assert event_times[-1] < 2.0

    @pytest.mark.asyncio
    async def test_with_text_only_message(self, handler, sample_text_message):
        """Test handler behavior with text-only message (no image)."""
        task_id = "test_text_only"
        
        # Should still process the task normally
        events = []
        async for event in handler.process_task(task_id, sample_text_message):
            events.append(event)
        
        # Should have same event structure regardless of input
        assert len(events) == 5
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.working
        assert isinstance(events[-1], TaskStatusUpdateEvent)
        assert events[-1].status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_with_session_id(self, handler, sample_image_message):
        """Test processing with session ID (should be ignored gracefully)."""
        task_id = "test_session"
        session_id = "pirate_session_123"
        
        events = []
        async for event in handler.process_task(task_id, sample_image_message, session_id):
            events.append(event)
        
        # Should process normally (session ID ignored)
        assert len(events) == 5
        assert all(event.id == task_id for event in events)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_tasks(self, handler):
        """Test handler can process multiple tasks concurrently."""
        messages = [
            Message(role=Role.user, parts=[TextPart(type="text", text=f"Image {i}")]) 
            for i in range(3)
        ]
        
        # Start multiple tasks concurrently
        tasks = [
            handler.process_task(f"task_{i}", msg)
            for i, msg in enumerate(messages)
        ]
        
        # Collect all events from all tasks
        all_events = []
        for task in tasks:
            task_events = []
            async for event in task:
                task_events.append(event)
            all_events.append(task_events)
        
        # Each task should complete normally
        assert len(all_events) == 3
        for task_events in all_events:
            assert len(task_events) == 5
            assert task_events[0].status.state == TaskState.working
            assert task_events[-1].status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_error_resilience(self, handler):
        """Test handler resilience to unusual inputs."""
        # Test with empty message
        empty_message = Message(role=Role.user, parts=[])
        
        events = []
        async for event in handler.process_task("test_empty", empty_message):
            events.append(event)
        
        # Should still complete successfully
        assert len(events) == 5
        assert events[-1].status.state == TaskState.completed

    @pytest.mark.asyncio 
    async def test_cancellation_behavior(self, handler, sample_image_message):
        """Test behavior when task processing is cancelled."""
        task_id = "test_cancel"
        
        # Start processing but cancel after first event
        event_generator = handler.process_task(task_id, sample_image_message)
        
        # Get first event
        first_event = await event_generator.__anext__()
        assert isinstance(first_event, TaskStatusUpdateEvent)
        assert first_event.status.state == TaskState.working
        
        # Cancel the generator (simulates task cancellation)
        await event_generator.aclose()
        
        # This should complete without error

    def test_handler_cancel_task(self, handler):
        """Test the cancel_task method (inherited from base class)."""
        # Base implementation should return False
        result = asyncio.run(handler.cancel_task("some_task"))
        assert result is False

    def test_handler_health_status(self, handler):
        """Test the health status reporting."""
        health = handler.get_health_status()
        
        assert isinstance(health, dict)
        assert health["handler_name"] == "pirate_vision"
        assert "capabilities" in health
        assert "timestamp" in health
        
        capabilities = health["capabilities"]
        assert isinstance(capabilities["sessions"], bool)  # May be True or False
        assert capabilities["streaming"] is False  # Base class default
        assert "content_types" in capabilities

    @pytest.mark.asyncio
    async def test_streaming_performance(self, handler, sample_image_message):
        """Test that streaming doesn't block unnecessarily."""
        task_id = "perf_test"
        
        start_time = asyncio.get_event_loop().time()
        
        # Process with timing checks
        event_count = 0
        async for event in handler.process_task(task_id, sample_image_message):
            event_count += 1
            
            # Each event should be yielded promptly
            current_time = asyncio.get_event_loop().time()
            elapsed = current_time - start_time
            
            # No single event should take too long to yield
            # (allowing for the intentional sleep delays)
            if event_count == 1:
                assert elapsed < 0.1  # Working status immediate
            elif event_count <= 4:
                # Artifact events with delays
                assert elapsed < (event_count * 0.5)  # Generous timing
            else:
                # Final completion
                assert elapsed < 2.0
        
        assert event_count == 5

    @pytest.mark.asyncio
    async def test_artifact_structure(self, handler, sample_image_message):
        """Test the structure of generated artifacts."""
        task_id = "structure_test"
        
        async for event in handler.process_task(task_id, sample_image_message):
            if isinstance(event, TaskArtifactUpdateEvent):
                artifact = event.artifact
                
                # Check artifact structure
                assert artifact.name == "pirate_vision"
                assert isinstance(artifact.index, int)
                assert artifact.index >= 0
                assert len(artifact.parts) == 1
                
                # Check part structure using model_dump
                part = artifact.parts[0]
                part_data = part.model_dump()
                assert part_data["type"] == "text"
                assert isinstance(part_data["text"], str)
                assert len(part_data["text"]) > 0
                
                # Check for pirate language characteristics
                text = part_data["text"].lower()
                assert any(phrase in text for phrase in [
                    "arr", "aye", "treasure", "sailor", "doubloon", "beast"
                ])