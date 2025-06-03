# #!/usr/bin/env python3
# # a2a_server/session/image_session_manager.py
# """
# Image-aware session management that optimizes context usage.

# Features:
# - Automatic image detection from tool calls
# - Smart summarization of images to minimize context
# - Hierarchical storage with parent/child relationships
# - Context-aware image inclusion based on user queries
# - Token-efficient context management
# """

# import logging
# import re
# from typing import Dict, List, Any, Optional, Tuple
# from datetime import datetime

# from a2a_json_rpc.spec import Artifact
# from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
# from a2a_server.session.models import (
#     ImageArtifact, 
#     ImageSessionMetadata,
#     ImageAnalysisRequest,
#     ImageAnalysisResult,
#     create_image_artifact_from_tool
# )

# logger = logging.getLogger(__name__)

# class ImageSessionManager:
#     """Manages images within conversation sessions with smart context optimization."""
    
#     def __init__(self, vision_agent: Optional[ChukAgent] = None):
#         self.vision_agent = vision_agent
#         self.image_store: Dict[str, ImageArtifact] = {}
#         self.session_metadata: Dict[str, ImageSessionMetadata] = {}
        
#     async def process_tool_response(
#         self, 
#         session_id: str,
#         tool_name: str, 
#         tool_response: str
#     ) -> Optional[ImageArtifact]:
#         """
#         Process tool response and extract any images.
        
#         Args:
#             session_id: Current session ID
#             tool_name: Name of the tool that returned data
#             tool_response: The tool's response (may contain image data)
            
#         Returns:
#             ImageArtifact if image was found and processed
#         """
#         # Create image artifact from tool response
#         artifact = create_image_artifact_from_tool(tool_name, tool_response)
#         if not artifact:
#             return None
            
#         # Store the image
#         self.image_store[artifact.id] = artifact
        
#         # Update session metadata
#         if session_id not in self.session_metadata:
#             self.session_metadata[session_id] = ImageSessionMetadata(session_id)
        
#         size_info = artifact.get_size_estimate()
#         self.session_metadata[session_id].add_image(artifact.id, size_info["estimated_mb"])
        
#         # Auto-summarize the image
#         if self.vision_agent:
#             await self._analyze_image(artifact)
        
#         logger.info(f"Processed image {artifact.id} from tool {tool_name} in session {session_id}")
#         return artifact
    
#     async def _analyze_image(self, artifact: ImageArtifact) -> Optional[ImageAnalysisResult]:
#         """Generate analysis of the image using vision model - PROPER FIX."""
#         if not self.vision_agent:
#             logger.info("No vision agent available for image analysis")
#             return None
            
#         try:
#             logger.info(f"Starting vision analysis for image {artifact.id}")
            
#             # Create vision messages with proper multimodal format
#             vision_messages = [
#                 {
#                     "role": "user", 
#                     "content": [
#                         {
#                             "type": "text",
#                             "text": "Analyze this image and provide a concise description of what you see. Focus on the main visual elements, structure, and purpose."
#                         },
#                         {
#                             "type": "image_url",
#                             "image_url": {
#                                 "url": f"data:{artifact.mime_type};base64,{artifact.image_data}"
#                             }
#                         }
#                     ]
#                 }
#             ]
            
#             logger.info("Calling vision agent generate_response")
            
#             # CRITICAL FIX: Handle the ChukAgent's generate_response properly
#             response = self.vision_agent.generate_response(vision_messages)
            
#             # Handle multiple levels of awaiting if needed
#             while hasattr(response, '__await__'):
#                 logger.info("Response is a coroutine, awaiting it")
#                 response = await response
            
#             logger.info(f"Vision response type after await: {type(response)}")
            
#             analysis_text = ""
            
#             # Handle async generator (streaming)
#             if hasattr(response, "__aiter__"):
#                 logger.info("Processing streaming response")
#                 async for chunk in response:
#                     delta = chunk.get("response", "")
#                     if delta:
#                         analysis_text += delta
#                 logger.info(f"Streaming complete: {len(analysis_text)} chars")
                
#             # Handle direct dict response
#             elif isinstance(response, dict):
#                 analysis_text = response.get("response", "")
#                 logger.info(f"Dict response: {len(analysis_text)} chars")
                
#             # Handle string response
#             elif isinstance(response, str):
#                 analysis_text = response
#                 logger.info(f"String response: {len(analysis_text)} chars")
                
#             else:
#                 # Handle any remaining coroutines or unexpected types
#                 logger.warning(f"Unexpected response type: {type(response)}")
#                 # Try one more await in case it's a nested coroutine
#                 try:
#                     if hasattr(response, '__await__'):
#                         response = await response
#                         if isinstance(response, dict):
#                             analysis_text = response.get("response", "")
#                         else:
#                             analysis_text = str(response)
#                     else:
#                         analysis_text = str(response)
#                 except Exception as e:
#                     logger.warning(f"Failed to extract from response: {e}")
#                     analysis_text = f"Image analysis of {artifact.source} - visual content with structured elements"
            
#             # Ensure we have some analysis text
#             if not analysis_text or analysis_text.strip() == "":
#                 logger.warning("No analysis text generated, using fallback")
#                 analysis_text = f"Image analysis of {artifact.source} - visual content with structured elements"
            
#             # Parse and update artifact
#             tags = self._extract_tags_from_analysis(analysis_text)
#             artifact.update_analysis(analysis_text, tags)
            
#             result = ImageAnalysisResult(
#                 image_id=artifact.id,
#                 analysis_type="summary",
#                 summary=analysis_text,
#                 tags=tags
#             )
            
#             logger.info(f"SUCCESS: Generated analysis for {artifact.id}: {analysis_text[:100]}...")
#             return result
            
#         except Exception as e:
#             logger.error(f"Vision analysis failed for {artifact.id}: {e}")
#             logger.exception("Full traceback:")
            
#             # Graceful fallback
#             fallback = "Image content with visual elements - analysis unavailable"
#             artifact.update_analysis(fallback)
#             return None
        
#     def _extract_tags_from_analysis(self, analysis: str) -> List[str]:
#         """Extract tags from analysis text."""
#         # Simple tag extraction - look for keywords
#         common_tags = [
#             'person', 'people', 'man', 'woman', 'child',
#             'building', 'house', 'car', 'road', 'tree', 'nature',
#             'text', 'document', 'chart', 'graph', 'diagram',
#             'food', 'animal', 'landscape', 'indoor', 'outdoor',
#             'screenshot', 'interface', 'website', 'application',
#             'table', 'data', 'visualization', 'map', 'network', 'node'
#         ]
        
#         tags = []
#         analysis_lower = analysis.lower()
        
#         for tag in common_tags:
#             if tag in analysis_lower:
#                 tags.append(tag)
        
#         return tags[:5]  # Limit to 5 tags
    
#     def should_include_images(self, user_message: str) -> bool:
#         """
#         Determine if user query requires full image analysis (not just summaries).
        
#         This is more precise than before - only returns True when user is actively
#         asking about visual content, not just mentioning image-related words.
#         """
#         message_lower = user_message.lower().strip()
        
#         # Direct image analysis requests - definitely need full images
#         direct_analysis_patterns = [
#             r'\b(describe|analyze|explain|tell me about).*(image|picture|photo|diagram|chart|screenshot)\b',
#             r'\b(what.*see|what.*shown|what.*displayed)\b',
#             r'\b(describe|analyze|explain).*(this|the)\b',  # "describe this", "analyze the", etc.
#             r'\bin.*the.*(image|picture|photo|diagram|chart)\b',
#             r'\bfrom.*the.*(image|picture|photo|diagram|chart)\b',
#             r'\blook.*at.*(this|the)\b',
#             r'\bshow.*me.*(details|what)\b',
#         ]
        
#         for pattern in direct_analysis_patterns:
#             if re.search(pattern, message_lower, re.IGNORECASE):
#                 logger.info(f"DEBUG: Direct image analysis pattern matched: {pattern}")
#                 return True
        
#         # Single word commands that likely refer to recent images
#         single_word_image_commands = [
#             'describe', 'analyze', 'explain', 'summarize', 'details'
#         ]
        
#         words = message_lower.split()
#         if len(words) <= 2 and any(cmd in words for cmd in single_word_image_commands):
#             logger.info(f"DEBUG: Single word image command detected: {words}")
#             return True
        
#         # Questions about visual elements
#         visual_question_patterns = [
#             r'\bhow many\b.*\b(nodes|elements|items|components)\b',
#             r'\bwhat.*color\b',
#             r'\bwhat.*size\b',
#             r'\bwhere.*located\b',
#             r'\bhow.*connected\b',
#             r'\bwhat.*layout\b',
#             r'\bwhat.*structure\b',
#             r'\bcan you see\b',
#         ]
        
#         for pattern in visual_question_patterns:
#             if re.search(pattern, message_lower, re.IGNORECASE):
#                 logger.info(f"DEBUG: Visual question pattern matched: {pattern}")
#                 return True
        
#         logger.info(f"DEBUG: No image analysis patterns matched for: {message_lower}")
#         return False

#     def get_context_level(self, user_message: str) -> str:
#         """
#         Determine what level of image context is needed.
        
#         Returns:
#             'full' - Full image analysis needed
#             'summary' - Brief summaries sufficient  
#             'minimal' - Just mention images exist
#             'none' - No image context needed
#         """
#         if not user_message:
#             return 'none'
        
#         # Check if user is asking about images
#         if self.should_include_images(user_message):
#             return 'full'
        
#         message_lower = user_message.lower()
        
#         # Check if user is asking questions that might benefit from image awareness
#         contextual_patterns = [
#             r'\bwhat.*we.*discuss\b',
#             r'\bwhat.*happen\b',
#             r'\bprevious\b',
#             r'\bearlier\b',
#             r'\bbefore\b',
#             r'\bcontext\b',
#             r'\bhistory\b',
#             r'\bwhat.*did.*we\b',
#             r'\bremember\b',
#         ]
        
#         for pattern in contextual_patterns:
#             if re.search(pattern, message_lower, re.IGNORECASE):
#                 return 'summary'
        
#         # Check if it's a completely unrelated query
#         unrelated_patterns = [
#             r'\bweather\b',
#             r'\btime\b',
#             r'\bcalculate\b',
#             r'\bmath\b',
#             r'\bcode\b',
#             r'\bprogram\b',
#             r'\bwrite.*function\b',
#             r'\bhow.*to.*\w+\b',  # "how to do X"
#             r'\bdefine\b',
#             r'\bexplain.*concept\b',
#         ]
        
#         for pattern in unrelated_patterns:
#             if re.search(pattern, message_lower, re.IGNORECASE):
#                 return 'none'
        
#         # Default to minimal awareness for ambiguous queries
#         return 'minimal'
    
#     def get_session_context(
#         self, 
#         session_id: str, 
#         include_full_images: bool = False
#     ) -> List[Artifact]:
#         """
#         Get image artifacts for session context.
        
#         Args:
#             session_id: Session to get images for
#             include_full_images: Whether to include full image data
            
#         Returns:
#             List of image artifacts
#         """
#         if session_id not in self.session_metadata:
#             return []
        
#         metadata = self.session_metadata[session_id]
#         artifacts = []
        
#         for image_id in metadata.image_ids:
#             if image_id in self.image_store:
#                 artifact = self.image_store[image_id]
#                 artifacts.append(artifact.to_artifact(include_full_images))
        
#         return artifacts
    
#     async def get_images_for_query(
#         self, 
#         session_id: str, 
#         user_query: str
#     ) -> Tuple[List[Artifact], bool]:
#         """
#         Get relevant images for a user query with smart context optimization.
        
#         Returns:
#             Tuple of (artifacts, should_include_full_images)
#         """
#         if session_id not in self.session_metadata:
#             return [], False
        
#         # Use smart detection to determine if full images are needed
#         include_full = self.should_include_images(user_query)
#         context_level = self.get_context_level(user_query)
        
#         logger.info(f"DEBUG: Query context level: {context_level}, include_full: {include_full}")
        
#         # Only get artifacts if context is needed
#         if context_level == 'none':
#             return [], False
        
#         artifacts = self.get_session_context(session_id, include_full)
        
#         # Mark that an image query was made (for analytics)
#         if include_full and artifacts:
#             self.session_metadata[session_id].mark_image_query()
        
#         return artifacts, include_full
    
#     def get_image_stats(self, session_id: Optional[str] = None) -> Dict[str, Any]:
#         """Get statistics about stored images."""
#         if session_id:
#             if session_id not in self.session_metadata:
#                 return {"total_images": 0, "total_size_mb": 0}
            
#             metadata = self.session_metadata[session_id]
#             images = [self.image_store[id] for id in metadata.image_ids if id in self.image_store]
#         else:
#             images = list(self.image_store.values())
        
#         return {
#             "total_images": len(images),
#             "total_size_mb": sum(
#                 img.get_size_estimate()["estimated_mb"] for img in images
#             ),
#             "sources": list(set(img.source for img in images)),
#             "with_summaries": sum(1 for img in images if img.summary),
#             "by_session": {
#                 sid: metadata.to_dict() 
#                 for sid, metadata in self.session_metadata.items()
#             } if not session_id else {}
#         }
    
#     def cleanup_session(self, session_id: str) -> None:
#         """Clean up images for a session."""
#         if session_id not in self.session_metadata:
#             return
        
#         metadata = self.session_metadata[session_id]
#         image_ids = metadata.image_ids.copy()
        
#         # Remove images that are only in this session
#         for image_id in image_ids:
#             # Check if image is used in other sessions
#             used_elsewhere = any(
#                 image_id in other_metadata.image_ids
#                 for other_session, other_metadata in self.session_metadata.items()
#                 if other_session != session_id
#             )
            
#             if not used_elsewhere and image_id in self.image_store:
#                 del self.image_store[image_id]
        
#         del self.session_metadata[session_id]
#         logger.info(f"Cleaned up images for session {session_id}")

# # Factory function for easy integration
# def create_image_session_manager(
#     vision_model: str = "gpt-4o",
#     provider: str = "openai", 
#     vision_config: Optional[Dict[str, Any]] = None
# ) -> ImageSessionManager:
#     """
#     Create an image session manager with vision capabilities.
#     """
#     try:
#         from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
#         from chuk_llm.llm.configuration.provider_config import ProviderConfig
        
#         logger.info(f"Creating vision agent with {provider}/{vision_model}")
        
#         # Create provider config if provided
#         config = Nones
#         if vision_config:
#             config = ProviderConfig(**vision_config)
#             logger.info(f"Using custom vision config")
#         else:
#             logger.info(f"Using default config")
        
#         vision_agent = ChukAgent(
#             name="vision_analyzer",
#             provider=provider,
#             model=vision_model,
#             config=config,
#             description="Analyzes images for session context",
#             instruction="You are an image analysis assistant. Provide concise, informative descriptions of images.",
#             streaming=False,  # Force non-streaming for consistent handling
#             enable_tools=False  # No tools needed for vision analysis
#         )
        
#         logger.info(f"Vision agent created successfully with {provider}/{vision_model}")
#         return ImageSessionManager(vision_agent)
        
#     except Exception as e:
#         logger.error(f"Failed to create vision agent: {e}")
#         logger.exception("Full traceback:")
#         return ImageSessionManager(None)