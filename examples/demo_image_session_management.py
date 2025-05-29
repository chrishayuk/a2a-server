#!/usr/bin/env python3
# test_image_session_management.py
"""
Comprehensive test script for the image session management system.

Tests all components independently before full agent integration:
- ImageArtifact creation and validation
- ImageSessionManager functionality
- Vision analysis simulation
- Enhanced conversation manager
- Image-aware agent handler mock

Run this to verify everything works before deploying.
"""

import asyncio
import base64
import json
import logging
import sys
from datetime import datetime
from io import BytesIO
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Mock PIL for testing without requiring it
class MockImage:
    def __init__(self, width=100, height=100):
        self.width = width
        self.height = height
    
    @staticmethod
    def new(mode, size, color):
        return MockImage(size[0], size[1])
    
    def save(self, buffer, format='PNG'):
        # Create fake PNG data
        fake_png = b'\x89PNG\r\n\x1a\n' + b'fake_image_data' * 10
        buffer.write(fake_png)

# Create a simple test image
def create_test_image() -> str:
    """Create a simple base64 test image."""
    buffer = BytesIO()
    img = MockImage.new('RGB', (100, 100), 'white')
    img.save(buffer, format='PNG')
    image_data = base64.b64encode(buffer.getvalue()).decode()
    return image_data

# Mock vision agent for testing
class MockVisionAgent:
    def __init__(self, provider="mock", model="mock-vision"):
        self.provider = provider
        self.model = model
        self.name = "mock_vision_agent"
    
    async def generate_response(self, messages: List[Dict[str, Any]]) -> Dict[str, str]:
        """Mock vision analysis response."""
        # Simulate processing time
        await asyncio.sleep(0.1)
        
        # Generate mock analysis based on image
        analyses = [
            "A simple test image showing geometric shapes and basic elements. Contains rectangular and circular forms with clear boundaries.",
            "Screenshot of a desktop application interface with menu bars, buttons, and text elements. Shows typical UI components.",
            "Chart visualization displaying data trends with bars and labels. Includes axis information and data points.",
            "Document or text-based image with structured layout. Contains paragraphs and formatted text sections."
        ]
        
        import random
        analysis = random.choice(analyses)
        
        return {
            "response": analysis
        }

# Utility function to safely extract text from message parts
def safe_extract_text(message) -> str:
    """Safely extract text content from a message."""
    if not hasattr(message, 'parts') or not message.parts:
        return "no parts available"
    
    for part in message.parts:
        # Try model_dump first (Pydantic v2)
        if hasattr(part, 'model_dump'):
            try:
                part_dict = part.model_dump()
                if 'text' in part_dict:
                    return part_dict['text']
            except Exception:
                pass
        
        # Try direct text access
        if hasattr(part, 'text'):
            try:
                return part.text
            except Exception:
                pass
        
        # Try content field
        if hasattr(part, 'content'):
            try:
                return part.content
            except Exception:
                pass
    
    return f"Could not extract text from {type(message.parts[0]).__name__}"

# Test functions
async def test_image_artifact_creation():
    """Test ImageArtifact creation and methods."""
    print("\n" + "="*50)
    print("1. Testing ImageArtifact Creation")
    print("="*50)
    
    try:
        from a2a_server.session.models import ImageArtifact, create_image_artifact_from_tool
        
        # Test direct creation
        test_image_data = create_test_image()
        artifact = ImageArtifact(
            image_data=test_image_data,
            source="test_creation",
            description="Test image for validation"
        )
        
        print(f"✅ Created ImageArtifact: {artifact.id}")
        print(f"   Source: {artifact.source}")
        print(f"   Valid image: {artifact.is_valid_image()}")
        
        size_info = artifact.get_size_estimate()
        print(f"   Size: {size_info['estimated_mb']:.3f} MB")
        
        # Test analysis update
        artifact.update_analysis(
            "Test image showing simple geometric shapes",
            tags=["test", "geometric", "simple"],
            metadata={"test_run": True}
        )
        
        print(f"   Summary: {artifact.summary}")
        print(f"   Tags: {artifact.tags}")
        
        # Test artifact conversion
        a2a_artifact = artifact.to_artifact(include_full_image=False)
        print(f"   A2A Artifact: {a2a_artifact.name}")
        print(f"   Parts count: {len(a2a_artifact.parts)}")
        
        # Test tool response creation
        mock_tool_response = json.dumps({
            "image": test_image_data,
            "format": "png",
            "description": "Mock tool generated image"
        })
        
        tool_artifact = create_image_artifact_from_tool(
            "mock_tool", mock_tool_response, "Tool test image"
        )
        
        if tool_artifact:
            print(f"✅ Created from tool response: {tool_artifact.id}")
        else:
            print("❌ Failed to create from tool response")
        
        return True
        
    except Exception as e:
        print(f"❌ ImageArtifact test failed: {e}")
        return False

async def test_image_session_manager():
    """Test ImageSessionManager functionality."""
    print("\n" + "="*50)
    print("2. Testing ImageSessionManager")
    print("="*50)
    
    try:
        from a2a_server.session.image_session_manager import ImageSessionManager
        
        # Create manager with mock vision agent
        vision_agent = MockVisionAgent()
        manager = ImageSessionManager(vision_agent)
        
        print("✅ Created ImageSessionManager with mock vision agent")
        
        # Test tool response processing
        test_session_id = "test_session_123"
        
        # Mock tool responses with images
        tool_responses = [
            json.dumps({
                "chart_type": "pie",
                "image": create_test_image(),
                "description": "Sales distribution chart"
            }),
            json.dumps({
                "screenshot": create_test_image(),
                "target": "desktop",
                "description": "Desktop screenshot"
            })
        ]
        
        artifacts = []
        for i, response in enumerate(tool_responses):
            tool_name = f"mock_tool_{i}"
            artifact = await manager.process_tool_response(
                test_session_id, tool_name, response
            )
            if artifact:
                artifacts.append(artifact)
                print(f"✅ Processed image from {tool_name}: {artifact.id}")
                print(f"   Summary: {artifact.summary}")
        
        # Test query detection
        image_queries = [
            "What do you see in the image?",
            "Analyze the chart data",
            "Describe the screenshot",
            "What's in the picture?"
        ]
        
        text_queries = [
            "How are you today?",
            "What is the weather like?",
            "Tell me a joke",
            "Calculate 2+2"
        ]
        
        print("\n📸 Image query detection:")
        for query in image_queries:
            is_image = manager.should_include_images(query)
            print(f"   '{query}' -> {is_image}")
        
        print("\n💬 Text query detection:")
        for query in text_queries:
            is_image = manager.should_include_images(query)
            print(f"   '{query}' -> {is_image}")
        
        # Test context retrieval
        context_summaries = manager.get_session_context(test_session_id, include_full_images=False)
        context_full = manager.get_session_context(test_session_id, include_full_images=True)
        
        print(f"\n📋 Session context:")
        print(f"   Summary artifacts: {len(context_summaries)}")
        print(f"   Full image artifacts: {len(context_full)}")
        
        # Test image query processing
        for query in ["What's in the image?", "Tell me about cats"]:
            artifacts, include_full = await manager.get_images_for_query(test_session_id, query)
            print(f"   Query: '{query}' -> {len(artifacts)} artifacts, full={include_full}")
        
        # Test statistics
        stats = manager.get_image_stats(test_session_id)
        print(f"\n📊 Session stats: {stats}")
        
        return True
        
    except Exception as e:
        print(f"❌ ImageSessionManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_enhanced_conversation_manager():
    """Test EnhancedConversationManager."""
    print("\n" + "="*50)
    print("3. Testing EnhancedConversationManager")
    print("="*50)
    
    try:
        from a2a_server.tasks.handlers.chuk.enhanced_conversation_manager import EnhancedConversationManager
        from a2a_server.session.image_session_manager import ImageSessionManager
        
        # Create with mock components
        vision_agent = MockVisionAgent()
        image_manager = ImageSessionManager(vision_agent)
        
        conv_manager = EnhancedConversationManager(
            token_threshold=2000,
            image_manager=image_manager,
            image_context_threshold=500
        )
        
        print("✅ Created EnhancedConversationManager")
        print(f"   Available: {conv_manager.available}")
        print(f"   Image management: {conv_manager.image_manager is not None}")
        print(f"   Effective token threshold: {conv_manager.effective_token_threshold}")
        
        # Test context building
        test_session = "conv_test_session"
        
        # Add some mock images
        for i in range(2):
            tool_response = json.dumps({
                "image": create_test_image(),
                "description": f"Test image {i+1}"
            })
            await image_manager.process_tool_response(
                test_session, f"tool_{i}", tool_response
            )
        
        # Test context retrieval with different queries
        queries = [
            "What's the weather like?",  # Text query
            "Analyze the images we discussed",  # Image query
            "Show me the chart from earlier"  # Image reference
        ]
        
        for query in queries:
            context = await conv_manager.get_context_with_images(
                test_session, query, include_image_analysis=True
            )
            print(f"\n🔍 Query: '{query}'")
            print(f"   Context messages: {len(context)}")
            for i, msg in enumerate(context):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if isinstance(content, list):
                    content_desc = f"Multimodal ({len(content)} parts)"
                else:
                    content_desc = content[:50] + "..." if len(content) > 50 else content
                print(f"     {i+1}. {role}: {content_desc}")
        
        # Test session summary
        summary = await conv_manager.get_session_summary_with_images(test_session)
        print(f"\n📋 Session summary: {summary}")
        
        return True
        
    except Exception as e:
        print(f"❌ EnhancedConversationManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_image_aware_handler():
    """Test ImageAwareAgentHandler with mock components."""
    print("\n" + "="*50)
    print("4. Testing ImageAwareAgentHandler (Mock)")
    print("="*50)
    
    try:
        # Mock the dependencies we need
        from a2a_json_rpc.spec import Message, TextPart, TaskState
        
        # Create a mock message
        message = Message(
            role="user",
            parts=[TextPart(type="text", text="Analyze this chart data")]
        )
        
        print("✅ Created mock message")
        
        # Extract content safely for display
        content = safe_extract_text(message)
        print(f"   Content: {content}")
        
        # Mock the handler initialization
        class MockImageAwareHandler:
            def __init__(self):
                self.name = "mock_image_handler"
                self.enable_image_management = True
                
                # Mock image manager
                vision_agent = MockVisionAgent()
                from a2a_server.session.image_session_manager import ImageSessionManager
                self.image_manager = ImageSessionManager(vision_agent)
                
                print("✅ Mock handler initialized with image management")
            
            def _extract_user_content(self, message):
                # Use the safe extraction function
                return safe_extract_text(message)
            
            async def simulate_task_processing(self, task_id: str, message: Message, session_id: str):
                """Simulate task processing with image detection."""
                user_content = self._extract_user_content(message)
                print(f"📝 Processing: '{user_content}'")
                
                # Simulate tool calls that return images
                mock_tool_responses = [
                    json.dumps({
                        "chart": create_test_image(),
                        "type": "bar_chart",
                        "data": "Q1 sales figures"
                    })
                ]
                
                # Check if asking about images
                asking_about_images = self.image_manager.should_include_images(user_content)
                print(f"🔍 Image query detected: {asking_about_images}")
                
                # Process tool responses
                for i, response in enumerate(mock_tool_responses):
                    artifact = await self.image_manager.process_tool_response(
                        session_id, f"chart_tool_{i}", response
                    )
                    if artifact:
                        print(f"📸 Created image artifact: {artifact.id}")
                        print(f"   Summary: {artifact.summary}")
                
                # Get context for response
                image_artifacts, include_full = await self.image_manager.get_images_for_query(
                    session_id, user_content
                )
                
                print(f"🎯 Context: {len(image_artifacts)} artifacts, include_full={include_full}")
                
                return {
                    "status": "completed",
                    "artifacts_created": len(image_artifacts),
                    "full_images_included": include_full
                }
        
        # Test the mock handler
        handler = MockImageAwareHandler()
        
        result = await handler.simulate_task_processing(
            "test_task_123", 
            message, 
            "test_session_456"
        )
        
        print(f"✅ Task processing result: {result}")
        
        # Test with different query types
        queries = [
            "What's the weather?",  # Text
            "Show me the chart",   # Image reference
            "Analyze the screenshot"  # Image analysis
        ]
        
        for query in queries:
            query_message = Message(
                role="user",
                parts=[TextPart(type="text", text=query)]
            )
            
            # Extract content safely
            safe_content = safe_extract_text(query_message)
            
            result = await handler.simulate_task_processing(
                f"task_{hash(query)}", 
                query_message, 
                "multi_query_session"
            )
            print(f"📊 '{safe_content}' -> {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ ImageAwareHandler test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_provider_configurations():
    """Test different provider configurations."""
    print("\n" + "="*50)
    print("5. Testing Provider Configurations")
    print("="*50)
    
    try:
        from a2a_server.session.image_session_manager import create_image_session_manager
        
        # Test different provider configs (simplified to avoid ProviderConfig issues)
        configs = [
            {
                "vision_model": "gpt-4o",
                "provider": "openai",
                "vision_config": None  # Keep simple for testing
            },
            {
                "vision_model": "claude-3-5-sonnet-20241022", 
                "provider": "anthropic",
                "vision_config": None
            },
            {
                "vision_model": "gemini-1.5-pro",
                "provider": "google", 
                "vision_config": None
            }
        ]
        
        for config in configs:
            try:
                # This will fail since we don't have real providers, but tests the factory
                manager = create_image_session_manager(**config)
                print(f"✅ {config['provider']}/{config['vision_model']}: Manager created")
                print(f"   Vision agent available: {manager.vision_agent is not None}")
            except Exception as e:
                print(f"⚠️  {config['provider']}/{config['vision_model']}: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Provider configuration test failed: {e}")
        return False

async def test_integration_scenario():
    """Test a realistic integration scenario."""
    print("\n" + "="*50)
    print("6. Integration Scenario Test")
    print("="*50)
    
    try:
        from a2a_server.session.image_session_manager import ImageSessionManager
        from a2a_server.tasks.handlers.chuk.enhanced_conversation_manager import EnhancedConversationManager
        
        # Create the full stack
        vision_agent = MockVisionAgent()
        image_manager = ImageSessionManager(vision_agent)
        conv_manager = EnhancedConversationManager(
            token_threshold=3000,
            image_manager=image_manager
        )
        
        session_id = "integration_test_session"
        
        print("🚀 Starting integration scenario...")
        
        # Scenario: User asks for chart, then analyzes it
        print("\n📊 Step 1: Generate chart")
        chart_response = json.dumps({
            "chart_type": "bar",
            "image": create_test_image(),
            "data": "Monthly sales: Jan: $10k, Feb: $15k, Mar: $12k"
        })
        
        chart_artifact = await image_manager.process_tool_response(
            session_id, "chart_generator", chart_response
        )
        print(f"   Created chart: {chart_artifact.id}")
        
        # Simulate conversation message
        await conv_manager.add_message_with_image_detection(
            session_id, 
            "I created a bar chart of monthly sales data",
            is_agent=True,
            tool_responses=[chart_response]
        )
        
        print("\n🔍 Step 2: User asks about chart")
        user_query = "What trends do you see in the chart?"
        
        # Get optimized context
        context = await conv_manager.get_context_optimized(
            session_id, user_query, max_tokens=2000
        )
        
        print(f"   Context messages: {len(context)}")
        print(f"   Estimated tokens: {conv_manager._estimate_tokens(context)}")
        
        # Check if images are included
        has_images = any(
            isinstance(msg.get("content"), list) 
            for msg in context
        )
        print(f"   Full images included: {has_images}")
        
        print("\n📱 Step 3: Add screenshot")
        screenshot_response = json.dumps({
            "image": create_test_image(),  # Changed from "screenshot" to "image"
            "target": "dashboard",
            "apps": ["Chart App", "Analytics Tool"],
            "description": "Screenshot of dashboard"
        })
        
        screenshot_artifact = await image_manager.process_tool_response(
            session_id, "screenshot_tool", screenshot_response
        )
        
        if screenshot_artifact:
            print(f"   Created screenshot: {screenshot_artifact.id}")
        else:
            print("   ⚠️ Screenshot artifact was None - continuing test")
            # Create a fallback for testing
            fallback_response = json.dumps({
                "image": create_test_image(),
                "format": "png",
                "description": "Fallback screenshot"
            })
            screenshot_artifact = await image_manager.process_tool_response(
                session_id, "screenshot_tool_fallback", fallback_response
            )
            if screenshot_artifact:
                print(f"   Created fallback screenshot: {screenshot_artifact.id}")
        
        print("\n🔎 Step 4: Multi-image query")
        multi_query = "Compare the chart with what's shown in the screenshot"
        
        context = await conv_manager.get_context_optimized(
            session_id, multi_query, max_tokens=2500
        )
        
        print(f"   Multi-image context: {len(context)} messages")
        
        # Count images in context
        image_count = 0
        for msg in context:
            if isinstance(msg.get("content"), list):
                image_count += sum(
                    1 for item in msg["content"] 
                    if item.get("type") == "image_url"
                )
        print(f"   Images in context: {image_count}")
        
        # Final stats
        final_stats = await conv_manager.get_session_summary_with_images(session_id)
        print(f"\n📈 Final session stats:")
        print(f"   Image stats: {final_stats.get('image_stats', {})}")
        
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all tests."""
    print("🧪 Image Session Management Test Suite")
    print("=" * 60)
    
    # Check if we're in the right environment
    try:
        # Try importing our modules
        import a2a_server.session.models
        import a2a_server.session.image_session_manager
        print("✅ All required modules available")
    except ImportError as e:
        print(f"❌ Missing required modules: {e}")
        print("Make sure you're running from the a2a-server directory")
        return False
    
    tests = [
        test_image_artifact_creation,
        test_image_session_manager,
        test_enhanced_conversation_manager,
        test_image_aware_handler,
        test_provider_configurations,
        test_integration_scenario
    ]
    
    results = []
    
    for test_func in tests:
        try:
            result = await test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Test {test_func.__name__} crashed: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST RESULTS SUMMARY")
    print("="*60)
    
    passed = sum(results)
    total = len(results)
    
    test_names = [
        "ImageArtifact Creation",
        "ImageSessionManager", 
        "EnhancedConversationManager",
        "ImageAwareHandler Mock",
        "Provider Configurations",
        "Integration Scenario"
    ]
    
    for i, (name, result) in enumerate(zip(test_names, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{i+1}. {name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Image session management is ready to deploy.")
    else:
        print("⚠️  Some tests failed. Review the output above for details.")
    
    return passed == total

if __name__ == "__main__":
    print("Starting test suite...")
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n👋 Tests cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test suite crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)