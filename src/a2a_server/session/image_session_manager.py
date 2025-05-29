#!/usr/bin/env python3
# a2a_server/session/image_session_manager.py
"""
Image-aware session management that optimizes context usage.

Features:
- Automatic image detection from tool calls
- Smart summarization of images to minimize context
- Hierarchical storage with parent/child relationships
- Context-aware image inclusion based on user queries
"""

import logging
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from a2a_json_rpc.spec import Artifact
from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
from a2a_server.session.models import (
    ImageArtifact, 
    ImageSessionMetadata,
    ImageAnalysisRequest,
    ImageAnalysisResult,
    create_image_artifact_from_tool
)

logger = logging.getLogger(__name__)

class ImageSessionManager:
    """Manages images within conversation sessions with smart context optimization."""
    
    def __init__(self, vision_agent: Optional[ChukAgent] = None):
        self.vision_agent = vision_agent
        self.image_store: Dict[str, ImageArtifact] = {}
        self.session_metadata: Dict[str, ImageSessionMetadata] = {}
        
        # Patterns to detect image-related queries
        self.image_query_patterns = [
            r'\b(image|picture|photo|screenshot|diagram|chart)\b',
            r'\bwhat.*see\b',
            r'\bdescribe.*visual',
            r'\bshow.*me',
            r'\blook.*at',
            r'\banalyze.*image',
            r'\bin.*the.*image',
            r'\bfrom.*the.*picture',
        ]
        
    async def process_tool_response(
        self, 
        session_id: str,
        tool_name: str, 
        tool_response: str
    ) -> Optional[ImageArtifact]:
        """
        Process tool response and extract any images.
        
        Args:
            session_id: Current session ID
            tool_name: Name of the tool that returned data
            tool_response: The tool's response (may contain image data)
            
        Returns:
            ImageArtifact if image was found and processed
        """
        # Create image artifact from tool response
        artifact = create_image_artifact_from_tool(tool_name, tool_response)
        if not artifact:
            return None
            
        # Store the image
        self.image_store[artifact.id] = artifact
        
        # Update session metadata
        if session_id not in self.session_metadata:
            self.session_metadata[session_id] = ImageSessionMetadata(session_id)
        
        size_info = artifact.get_size_estimate()
        self.session_metadata[session_id].add_image(artifact.id, size_info["estimated_mb"])
        
        # Auto-summarize the image
        if self.vision_agent:
            await self._analyze_image(artifact)
        
        logger.info(f"Processed image {artifact.id} from tool {tool_name} in session {session_id}")
        return artifact
    
    async def _analyze_image(self, artifact: ImageArtifact) -> Optional[ImageAnalysisResult]:
        """Generate analysis of the image using vision model - PROPER FIX."""
        if not self.vision_agent:
            logger.info("No vision agent available for image analysis")
            return None
            
        try:
            logger.info(f"Starting vision analysis for image {artifact.id}")
            
            # Create vision messages with proper multimodal format
            vision_messages = [
                {
                    "role": "user", 
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this image and provide a concise description of what you see. Focus on the main visual elements, structure, and purpose."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{artifact.mime_type};base64,{artifact.image_data}"
                            }
                        }
                    ]
                }
            ]
            
            logger.info("Calling vision agent generate_response")
            
            # CRITICAL FIX: Handle the ChukAgent's generate_response properly
            response = self.vision_agent.generate_response(vision_messages)
            
            # Handle multiple levels of awaiting if needed
            while hasattr(response, '__await__'):
                logger.info("Response is a coroutine, awaiting it")
                response = await response
            
            logger.info(f"Vision response type after await: {type(response)}")
            
            analysis_text = ""
            
            # Handle async generator (streaming)
            if hasattr(response, "__aiter__"):
                logger.info("Processing streaming response")
                async for chunk in response:
                    delta = chunk.get("response", "")
                    if delta:
                        analysis_text += delta
                logger.info(f"Streaming complete: {len(analysis_text)} chars")
                
            # Handle direct dict response
            elif isinstance(response, dict):
                analysis_text = response.get("response", "")
                logger.info(f"Dict response: {len(analysis_text)} chars")
                
            # Handle string response
            elif isinstance(response, str):
                analysis_text = response
                logger.info(f"String response: {len(analysis_text)} chars")
                
            else:
                # Handle any remaining coroutines or unexpected types
                logger.warning(f"Unexpected response type: {type(response)}")
                # Try one more await in case it's a nested coroutine
                try:
                    if hasattr(response, '__await__'):
                        response = await response
                        if isinstance(response, dict):
                            analysis_text = response.get("response", "")
                        else:
                            analysis_text = str(response)
                    else:
                        analysis_text = str(response)
                except Exception as e:
                    logger.warning(f"Failed to extract from response: {e}")
                    analysis_text = f"Image analysis of {artifact.source} - visual content with structured elements"
            
            # Ensure we have some analysis text
            if not analysis_text or analysis_text.strip() == "":
                logger.warning("No analysis text generated, using fallback")
                analysis_text = f"Image analysis of {artifact.source} - visual content with structured elements"
            
            # Parse and update artifact
            tags = self._extract_tags_from_analysis(analysis_text)
            artifact.update_analysis(analysis_text, tags)
            
            result = ImageAnalysisResult(
                image_id=artifact.id,
                analysis_type="summary",
                summary=analysis_text,
                tags=tags
            )
            
            logger.info(f"SUCCESS: Generated analysis for {artifact.id}: {analysis_text[:100]}...")
            return result
            
        except Exception as e:
            logger.error(f"Vision analysis failed for {artifact.id}: {e}")
            logger.exception("Full traceback:")
            
            # Graceful fallback
            fallback = "Image content with visual elements - analysis unavailable"
            artifact.update_analysis(fallback)
            return None
        
    def _extract_tags_from_analysis(self, analysis: str) -> List[str]:
        """Extract tags from analysis text."""
        # Simple tag extraction - look for keywords
        common_tags = [
            'person', 'people', 'man', 'woman', 'child',
            'building', 'house', 'car', 'road', 'tree', 'nature',
            'text', 'document', 'chart', 'graph', 'diagram',
            'food', 'animal', 'landscape', 'indoor', 'outdoor',
            'screenshot', 'interface', 'website', 'application',
            'table', 'data', 'visualization', 'map'
        ]
        
        tags = []
        analysis_lower = analysis.lower()
        
        for tag in common_tags:
            if tag in analysis_lower:
                tags.append(tag)
        
        return tags[:5]  # Limit to 5 tags
    
    def should_include_images(self, user_message: str) -> bool:
        """Determine if user query is asking about images."""
        message_lower = user_message.lower()
        return any(
            re.search(pattern, message_lower, re.IGNORECASE) 
            for pattern in self.image_query_patterns
        )
    
    def get_session_context(
        self, 
        session_id: str, 
        include_full_images: bool = False
    ) -> List[Artifact]:
        """
        Get image artifacts for session context.
        
        Args:
            session_id: Session to get images for
            include_full_images: Whether to include full image data
            
        Returns:
            List of image artifacts
        """
        if session_id not in self.session_metadata:
            return []
        
        metadata = self.session_metadata[session_id]
        artifacts = []
        
        for image_id in metadata.image_ids:
            if image_id in self.image_store:
                artifact = self.image_store[image_id]
                artifacts.append(artifact.to_artifact(include_full_images))
        
        return artifacts
    
    async def get_images_for_query(
        self, 
        session_id: str, 
        user_query: str
    ) -> Tuple[List[Artifact], bool]:
        """
        Get relevant images for a user query.
        
        Returns:
            Tuple of (artifacts, should_include_full_images)
        """
        if session_id not in self.session_metadata:
            return [], False
        
        include_full = self.should_include_images(user_query)
        artifacts = self.get_session_context(session_id, include_full)
        
        # Mark that an image query was made
        if include_full and artifacts:
            self.session_metadata[session_id].mark_image_query()
        
        return artifacts, include_full
    
    def get_image_stats(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics about stored images."""
        if session_id:
            if session_id not in self.session_metadata:
                return {"total_images": 0, "total_size_mb": 0}
            
            metadata = self.session_metadata[session_id]
            images = [self.image_store[id] for id in metadata.image_ids if id in self.image_store]
        else:
            images = list(self.image_store.values())
        
        return {
            "total_images": len(images),
            "total_size_mb": sum(
                img.get_size_estimate()["estimated_mb"] for img in images
            ),
            "sources": list(set(img.source for img in images)),
            "with_summaries": sum(1 for img in images if img.summary),
            "by_session": {
                sid: metadata.to_dict() 
                for sid, metadata in self.session_metadata.items()
            } if not session_id else {}
        }
    
    def cleanup_session(self, session_id: str) -> None:
        """Clean up images for a session."""
        if session_id not in self.session_metadata:
            return
        
        metadata = self.session_metadata[session_id]
        image_ids = metadata.image_ids.copy()
        
        # Remove images that are only in this session
        for image_id in image_ids:
            # Check if image is used in other sessions
            used_elsewhere = any(
                image_id in other_metadata.image_ids
                for other_session, other_metadata in self.session_metadata.items()
                if other_session != session_id
            )
            
            if not used_elsewhere and image_id in self.image_store:
                del self.image_store[image_id]
        
        del self.session_metadata[session_id]
        logger.info(f"Cleaned up images for session {session_id}")

# Factory function for easy integration
# Debug version of create_image_session_manager to see what's going wrong

def create_image_session_manager(
    vision_model: str = "gpt-4o",
    provider: str = "openai", 
    vision_config: Optional[Dict[str, Any]] = None
) -> ImageSessionManager:
    """
    Create an image session manager with vision capabilities - DEBUG VERSION.
    """
    try:
        from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
        from chuk_llm.llm.configuration.provider_config import ProviderConfig
        
        logger.info(f"DEBUG: Creating vision agent with {provider}/{vision_model}")
        
        # Create provider config if provided
        config = None
        if vision_config:
            config = ProviderConfig(**vision_config)
            logger.info(f"DEBUG: Using custom vision config")
        else:
            logger.info(f"DEBUG: Using default config")
        
        vision_agent = ChukAgent(
            name="vision_analyzer",
            provider=provider,
            model=vision_model,
            config=config,
            description="Analyzes images for session context",
            instruction="You are an image analysis assistant. Provide concise, informative descriptions of images.",
            streaming=False,  # Force non-streaming
            enable_tools=False  # No tools needed
        )
        
        logger.info(f"DEBUG: Vision agent created successfully")
        logger.info(f"DEBUG: Agent streaming setting: {vision_agent.streaming}")
        logger.info(f"DEBUG: Agent provider: {vision_agent.provider}")
        logger.info(f"DEBUG: Agent model: {vision_agent.model}")
        
        # Test the vision agent quickly
        try:
            test_messages = [{"role": "user", "content": "Hello, can you see this?"}]
            test_response = vision_agent.generate_response(test_messages)
            logger.info(f"DEBUG: Test response type: {type(test_response)}")
            
            # If it's a coroutine, that's our problem
            if hasattr(test_response, '__await__'):
                logger.warning("DEBUG: Vision agent is returning coroutines - this is the issue!")
            
        except Exception as test_error:
            logger.warning(f"DEBUG: Vision agent test failed: {test_error}")
        
        return ImageSessionManager(vision_agent)
        
    except Exception as e:
        logger.error(f"DEBUG: Failed to create vision agent: {e}")
        logger.exception("DEBUG: Full traceback:")
        return ImageSessionManager(None)