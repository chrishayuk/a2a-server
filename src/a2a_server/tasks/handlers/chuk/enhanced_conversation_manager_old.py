# #!/usr/bin/env python3
# # a2a_server/tasks/handlers/chuk/enhanced_conversation_manager.py
# """
# Enhanced conversation manager with intelligent image context management.

# Integrates with the hierarchical session system to:
# - Store image summaries in parent sessions
# - Include full images only when needed
# - Optimize context window usage
# - Support vision-based conversation flows
# """

# import logging
# from typing import Dict, List, Any, Optional, Tuple

# from a2a_server.session.image_session_manager import ImageSessionManager
# from a2a_server.tasks.handlers.chuk.conversation_manager import ConversationManager

# logger = logging.getLogger(__name__)

# class EnhancedConversationManager(ConversationManager):
#     """
#     Enhanced conversation manager with smart image context handling.
    
#     Extends the base conversation manager to:
#     - Integrate image session management
#     - Optimize context with image summaries
#     - Include full images only when user asks image questions
#     - Support hierarchical session structure with image artifacts
#     """
    
#     def __init__(
#         self,
#         token_threshold: int = 4000,
#         summarization_strategy: str = "key_points",
#         agent=None,
#         image_manager: Optional[ImageSessionManager] = None,
#         vision_model: str = "gpt-4o",
#         image_context_threshold: int = 500  # Tokens to reserve for image summaries
#     ):
#         """
#         Initialize enhanced conversation manager.
        
#         Args:
#             token_threshold: Maximum tokens before session segmentation
#             summarization_strategy: Strategy for summarizing sessions
#             agent: Optional agent for generating summaries
#             image_manager: Optional image session manager
#             vision_model: Model to use for vision analysis
#             image_context_threshold: Tokens to reserve for image context
#         """
#         super().__init__(token_threshold, summarization_strategy, agent)
        
#         # Image management
#         self.image_manager = image_manager
#         self.vision_model = vision_model
#         self.image_context_threshold = image_context_threshold
        
#         # Adjust token threshold to account for image context
#         self.effective_token_threshold = token_threshold - image_context_threshold
        
#         logger.info(f"Enhanced conversation manager initialized with image support")
    
#     async def get_context_with_images(
#         self, 
#         external_session_id: str,
#         user_query: str,
#         include_image_analysis: bool = True
#     ) -> List[Dict[str, str]]:
#         """
#         Get conversation context optimized for image-aware conversations.
        
#         Args:
#             external_session_id: The external session ID
#             user_query: The current user query
#             include_image_analysis: Whether to analyze query for image relevance
            
#         Returns:
#             Optimized conversation context with smart image inclusion
#         """
#         # Get base conversation context
#         base_context = await self.get_context(external_session_id)
        
#         # If no image manager, return base context
#         if not self.image_manager:
#             return base_context
        
#         # Get image artifacts for this session
#         image_artifacts, include_full_images = await self.image_manager.get_images_for_query(
#             external_session_id, user_query
#         )
        
#         if not image_artifacts:
#             return base_context
        
#         # Build enhanced context
#         enhanced_context = []
        
#         # Add system message if present
#         if base_context and base_context[0].get("role") == "system":
#             enhanced_context.append(base_context[0])
#             base_context = base_context[1:]
        
#         # Add image context early in conversation
#         image_context = self._build_image_context(
#             image_artifacts, 
#             include_full_images,
#             user_query
#         )
        
#         if image_context:
#             enhanced_context.extend(image_context)
        
#         # Add rest of conversation
#         enhanced_context.extend(base_context)
        
#         return enhanced_context
    
#     def _build_image_context(
#         self, 
#         image_artifacts: List[Any], 
#         include_full_images: bool,
#         user_query: str
#     ) -> List[Dict[str, str]]:
#         """Build image context messages for conversation."""
#         if not image_artifacts:
#             return []
        
#         context_messages = []
        
#         if include_full_images:
#             # User is asking about images - include full image data
#             for artifact in image_artifacts:
#                 # Extract image data and summary
#                 image_content = []
#                 summary_text = ""
                
#                 for part in artifact.parts:
#                     if hasattr(part, 'type'):
#                         if part.type == "text" and hasattr(part, 'text'):
#                             summary_text += part.text + " "
#                         elif part.type == "image" and hasattr(part, 'data'):
#                             image_content.append({
#                                 "type": "image_url",
#                                 "image_url": {
#                                     "url": f"data:{getattr(part, 'mime_type', 'image/jpeg')};base64,{part.data}"
#                                 }
#                             })
                
#                 # Create multimodal message with image and summary
#                 if image_content:
#                     content = [
#                         {"type": "text", "text": f"Image available: {summary_text.strip()}"}
#                     ] + image_content
                    
#                     context_messages.append({
#                         "role": "user",
#                         "content": content
#                     })
#         else:
#             # Just include image summaries to save context
#             summaries = []
#             for artifact in image_artifacts:
#                 for part in artifact.parts:
#                     if hasattr(part, 'type') and part.type == "text" and hasattr(part, 'text'):
#                         summaries.append(part.text)
            
#             if summaries:
#                 combined_summary = "Images in this conversation: " + " | ".join(summaries)
#                 context_messages.append({
#                     "role": "system",
#                     "content": combined_summary
#                 })
        
#         return context_messages
    
#     async def add_message_with_image_detection(
#         self,
#         external_session_id: str,
#         message: str,
#         is_agent: bool = False,
#         tool_responses: Optional[List[str]] = None
#     ) -> bool:
#         """
#         Add message to session with automatic image detection from tool responses.
        
#         Args:
#             external_session_id: The external session ID
#             message: The message content
#             is_agent: Whether the message is from the agent
#             tool_responses: Optional tool responses that might contain images
            
#         Returns:
#             True if message was added successfully
#         """
#         # Add the message normally
#         success = await self.add_message(external_session_id, message, is_agent)
        
#         # Process any tool responses for images
#         if self.image_manager and tool_responses and success:
#             for i, response in enumerate(tool_responses):
#                 try:
#                     tool_name = f"tool_call_{i}"
#                     await self.image_manager.process_tool_response(
#                         external_session_id, tool_name, response
#                     )
#                 except Exception as e:
#                     logger.error(f"Error processing tool response for images: {e}")
        
#         return success
    
#     async def get_context_optimized(
#         self,
#         external_session_id: str,
#         user_query: str,
#         max_tokens: Optional[int] = None
#     ) -> List[Dict[str, str]]:
#         """
#         Get optimally sized context that fits within token limits.
        
#         Args:
#             external_session_id: The external session ID
#             user_query: Current user query
#             max_tokens: Maximum tokens for context (uses configured threshold if None)
            
#         Returns:
#             Optimized context that fits within token limits
#         """
#         target_tokens = max_tokens or self.effective_token_threshold
        
#         # Get full context with images
#         full_context = await self.get_context_with_images(external_session_id, user_query)
        
#         # Estimate token usage (rough approximation)
#         estimated_tokens = self._estimate_tokens(full_context)
        
#         if estimated_tokens <= target_tokens:
#             return full_context
        
#         # Need to optimize - try reducing image content first
#         if self.image_manager and self.image_manager.should_include_images(user_query):
#             # User is asking about images, keep them but maybe reduce conversation history
#             optimized_context = await self._optimize_with_images(
#                 external_session_id, user_query, target_tokens
#             )
#         else:
#             # Not asking about images, use summaries only
#             optimized_context = await self._optimize_without_full_images(
#                 external_session_id, user_query, target_tokens
#             )
        
#         return optimized_context
    
#     def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
#         """Rough token estimation for messages."""
#         total = 0
#         for msg in messages:
#             content = msg.get("content", "")
#             if isinstance(content, str):
#                 # Rough approximation: 1 token per 4 characters
#                 total += len(content) // 4
#             elif isinstance(content, list):
#                 for item in content:
#                     if item.get("type") == "text":
#                         total += len(item.get("text", "")) // 4
#                     elif item.get("type") == "image_url":
#                         # Images use significant tokens
#                         total += 1000  # Rough estimate for image tokens
#         return total
    
#     async def _optimize_with_images(
#         self,
#         external_session_id: str,
#         user_query: str,
#         target_tokens: int
#     ) -> List[Dict[str, str]]:
#         """Optimize context while keeping images since user is asking about them."""
#         # Get context with full images
#         full_context = await self.get_context_with_images(
#             external_session_id, user_query, include_image_analysis=True
#         )
        
#         # Keep system message and images, truncate conversation history
#         system_messages = [msg for msg in full_context if msg.get("role") == "system"]
#         image_messages = []
#         conversation_messages = []
        
#         for msg in full_context:
#             if msg.get("role") == "system":
#                 continue
#             elif isinstance(msg.get("content"), list):
#                 # Likely contains images
#                 image_messages.append(msg)
#             else:
#                 conversation_messages.append(msg)
        
#         # Start with system and image messages
#         optimized = system_messages + image_messages
#         current_tokens = self._estimate_tokens(optimized)
        
#         # Add conversation messages until we hit the limit
#         for msg in reversed(conversation_messages):
#             msg_tokens = self._estimate_tokens([msg])
#             if current_tokens + msg_tokens <= target_tokens:
#                 optimized.insert(-len(image_messages) if image_messages else len(optimized), msg)
#                 current_tokens += msg_tokens
#             else:
#                 break
        
#         return optimized
    
#     async def _optimize_without_full_images(
#         self,
#         external_session_id: str,
#         user_query: str,
#         target_tokens: int
#     ) -> List[Dict[str, str]]:
#         """Optimize context using image summaries instead of full images."""
#         # Get context with image summaries only
#         context = await self.get_context_with_images(
#             external_session_id, user_query, include_image_analysis=False
#         )
        
#         current_tokens = self._estimate_tokens(context)
        
#         if current_tokens <= target_tokens:
#             return context
        
#         # Need to truncate conversation history
#         system_messages = [msg for msg in context if msg.get("role") == "system"]
#         other_messages = [msg for msg in context if msg.get("role") != "system"]
        
#         # Keep recent messages that fit in token budget
#         optimized = system_messages.copy()
#         remaining_tokens = target_tokens - self._estimate_tokens(system_messages)
        
#         for msg in reversed(other_messages):
#             msg_tokens = self._estimate_tokens([msg])
#             if remaining_tokens >= msg_tokens:
#                 optimized.append(msg)
#                 remaining_tokens -= msg_tokens
#             else:
#                 break
        
#         # Ensure messages are in correct order
#         if len(optimized) > len(system_messages):
#             conversation_part = optimized[len(system_messages):]
#             conversation_part.reverse()
#             optimized = system_messages + conversation_part
        
#         return optimized
    
#     async def get_session_summary_with_images(self, external_session_id: str) -> Dict[str, Any]:
#         """Get comprehensive session summary including image information."""
#         base_summary = {
#             "conversation_available": self.available,
#             "image_management_available": self.image_manager is not None
#         }
        
#         if not self.available:
#             return base_summary
        
#         # Get conversation history
#         try:
#             history = await self.get_conversation_history(external_session_id)
#             token_usage = await self.get_token_usage(external_session_id)
            
#             base_summary.update({
#                 "message_count": len(history),
#                 "token_usage": token_usage
#             })
#         except Exception as e:
#             logger.error(f"Error getting conversation summary: {e}")
#             base_summary["conversation_error"] = str(e)
        
#         # Get image information
#         if self.image_manager:
#             try:
#                 image_stats = self.image_manager.get_image_stats(external_session_id)
#                 base_summary["image_stats"] = image_stats
#             except Exception as e:
#                 logger.error(f"Error getting image stats: {e}")
#                 base_summary["image_error"] = str(e)
        
#         return base_summary
    
#     async def cleanup_session(self, external_session_id: str) -> None:
#         """Clean up both conversation and image data for a session."""
#         # Clean up images first
#         if self.image_manager:
#             try:
#                 self.image_manager.cleanup_session(external_session_id)
#                 logger.info(f"Cleaned up images for session {external_session_id}")
#             except Exception as e:
#                 logger.error(f"Error cleaning up images for session {external_session_id}: {e}")
        
#         # Note: Base conversation cleanup would be handled by session lifecycle manager
#         logger.info(f"Session cleanup completed for {external_session_id}")

# # Factory function for easy integration
# def create_enhanced_conversation_manager(
#     agent=None,
#     token_threshold: int = 4000,
#     summarization_strategy: str = "key_points",
#     enable_image_management: bool = True,
#     vision_model: str = "gpt-4o",
#     vision_provider: str = "openai",
#     vision_config: Optional[Dict[str, Any]] = None
# ) -> EnhancedConversationManager:
#     """
#     Create an enhanced conversation manager with optional image support.
    
#     Args:
#         agent: Agent for conversation summarization
#         token_threshold: Token limit for conversation context
#         summarization_strategy: Strategy for summarizing conversations
#         enable_image_management: Whether to enable image session management
#         vision_model: Model to use for image analysis
#         vision_provider: Provider for vision model (openai, anthropic, google, etc.)
#         vision_config: Optional provider configuration for vision model
        
#     Returns:
#         Enhanced conversation manager instance
#     """
#     image_manager = None
    
#     if enable_image_management:
#         try:
#             from a2a_server.session.image_session_manager import create_image_session_manager
#             image_manager = create_image_session_manager(
#                 vision_model=vision_model,
#                 provider=vision_provider,
#                 vision_config=vision_config
#             )
#             logger.info(f"Image management enabled with {vision_provider}/{vision_model}")
#         except Exception as e:
#             logger.warning(f"Could not enable image management: {e}")
    
#     return EnhancedConversationManager(
#         token_threshold=token_threshold,
#         summarization_strategy=summarization_strategy,
#         agent=agent,
#         image_manager=image_manager,
#         vision_model=vision_model
#     )