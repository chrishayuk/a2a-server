# #!/usr/bin/env python3
# # a2a_server/tasks/handlers/chuk/image_aware_agent_handler.py
# """
# FIXED VERSION: Enhanced agent handler with intelligent image session management.
# """

# import json
# import logging
# from typing import AsyncGenerator, Optional, List, Dict, Any

# from a2a_server.tasks.task_handler import TaskHandler
# from a2a_server.session.image_session_manager import ImageSessionManager, create_image_session_manager
# from a2a_json_rpc.spec import (
#     Message, TaskStatus, TaskState, TaskStatusUpdateEvent, 
#     TaskArtifactUpdateEvent, Artifact, TextPart
# )

# logger = logging.getLogger(__name__)

# class ImageAwareAgentHandler(TaskHandler):
#     """
#     Agent handler with intelligent image session management - FIXED VERSION.
#     """
    
#     def __init__(
#         self, 
#         agent=None, 
#         name="image_aware_agent", 
#         enable_image_management: bool = True,
#         vision_model: str = "gpt-4o",
#         vision_provider: str = "openai",
#         vision_config: Optional[Dict[str, Any]] = None,
#         **kwargs
#     ):
#         super().__init__()
#         self.agent = None
#         self._name = name
        
#         # Initialize image management
#         self.enable_image_management = enable_image_management
#         self.image_manager: Optional[ImageSessionManager] = None
        
#         if self.enable_image_management:
#             try:
#                 self.image_manager = create_image_session_manager(
#                     vision_model=vision_model,
#                     provider=vision_provider,
#                     vision_config=vision_config
#                 )
#                 logger.info(f"Image session management enabled for {name} using {vision_provider}/{vision_model}")
#             except Exception as e:
#                 logger.warning(f"Could not enable image management: {e}")
#                 self.enable_image_management = False
        
#         # Load the agent (same as parent class)
#         if agent:
#             if hasattr(agent, 'process_message'):
#                 self.agent = agent
#                 logger.info(f"Using provided agent instance")
#             else:
#                 try:
#                     import importlib
#                     module_path, _, attr = agent.rpartition('.')
#                     module = importlib.import_module(module_path)
#                     self.agent = getattr(module, attr)
#                     logger.info(f"Loaded agent from {agent}")
#                 except (ImportError, AttributeError) as e:
#                     logger.error(f"Failed to load agent from {agent}: {e}")
    
#     @property
#     def name(self) -> str:
#         return self._name
    
#     @property
#     def supported_content_types(self) -> List[str]:
#         return ["text/plain", "multipart/mixed", "image/jpeg", "image/png"]
    
#     async def process_task(
#         self, 
#         task_id: str, 
#         message: Message, 
#         session_id: Optional[str] = None,
#         **kwargs
#         ) -> AsyncGenerator:
#         """
#         Process a task with intelligent image management - FIXED VERSION.
#         """
#         logger.info(f"DEBUG: Starting image-aware task processing for {task_id}")

#         if self.agent is None:
#             logger.error("No agent configured")
#             yield TaskStatusUpdateEvent(
#                 id=task_id,
#                 status=TaskStatus(state=TaskState.failed),
#                 final=True
#             )
#             return

#         try:
#             # Check if user is asking about images
#             user_content = self._extract_user_content(message)
#             logger.info(f"DEBUG: User content: {user_content}")
            
#             asking_about_images = False
#             image_artifacts = []
            
#             if self.image_manager and session_id:
#                 asking_about_images = self.image_manager.should_include_images(user_content)
#                 logger.info(f"DEBUG: Asking about images: {asking_about_images}")
                
#                 # Get relevant image artifacts for context
#                 image_artifacts, include_full_images = await self.image_manager.get_images_for_query(
#                     session_id, user_content
#                 )
                
#                 # CRITICAL FIX: Yield image artifacts for display AND modify the message
#                 if image_artifacts:
#                     logger.info(f"Including {len(image_artifacts)} image artifacts (full_images={include_full_images})")
#                     for img_artifact in image_artifacts:
#                         yield TaskArtifactUpdateEvent(id=task_id, artifact=img_artifact)
                    
#                     # MOST IMPORTANT: Modify the message to include image context
#                     message = self._enhance_message_with_images(message, image_artifacts, asking_about_images)
            
#             # Process the task with the agent (now with enhanced message)
#             tool_responses = []
#             event_count = 0
            
#             logger.info(f"DEBUG: Starting agent processing with enhanced message")
#             async for event in self.agent.process_message(task_id, message, session_id):
#                 event_count += 1
#                 logger.info(f"DEBUG: Event {event_count}: {type(event).__name__}")
                
#                 # Capture any tool responses for image processing
#                 if isinstance(event, TaskArtifactUpdateEvent):
#                     artifact_content = self._extract_artifact_content(event.artifact)
                    
#                     if self._looks_like_tool_response(artifact_content):
#                         logger.info(f"DEBUG: DETECTED TOOL RESPONSE!")
#                         tool_responses.append(artifact_content)
                
#                 yield event
            
#             logger.info(f"DEBUG: Agent processing complete. {len(tool_responses)} tool responses captured")
            
#             # Process any images from tool calls
#             if self.image_manager and session_id and tool_responses:
#                 logger.info(f"DEBUG: Processing {len(tool_responses)} tool responses for images")
#                 image_events = await self._process_tool_images(task_id, session_id, tool_responses)
#                 logger.info(f"DEBUG: Generated {len(image_events)} image events")
#                 for event in image_events:
#                     yield event

#         except Exception as e:
#             logger.error(f"Error in image-aware agent processing: {e}")
#             yield TaskStatusUpdateEvent(
#                 id=task_id,
#                 status=TaskStatus(state=TaskState.failed),
#                 final=True
#             )
    
#     def _enhance_message_with_images(
#         self, 
#         original_message: Message, 
#         image_artifacts: List[Artifact],
#         include_full_images: bool
#     ) -> Message:
#         """
#         CRITICAL FIX: Enhance the message with image context so the agent can see them.
#         """
#         if not image_artifacts:
#             return original_message
        
#         # Extract original text content
#         original_text = self._extract_user_content(original_message)
        
#         # Build image context description
#         image_context_parts = []
        
#         if include_full_images:
#             # User is asking about images - provide detailed context
#             image_context_parts.append("🔍 AVAILABLE IMAGES IN THIS CONVERSATION:")
#             image_context_parts.append("")
            
#             for i, artifact in enumerate(image_artifacts):
#                 # Extract image summary from artifact
#                 summary = self._extract_image_summary_from_artifact(artifact)
#                 image_context_parts.append(f"📊 Image {i+1}: {summary}")
                
#                 # Also add metadata if available
#                 if hasattr(artifact, 'metadata') and artifact.metadata:
#                     metadata = artifact.metadata
#                     if isinstance(metadata, dict):
#                         source = metadata.get('source', '')
#                         if source:
#                             image_context_parts.append(f"   Source: {source}")
            
#             image_context_parts.append("")
#             image_context_parts.append("ℹ️  Based on the above image analysis, please describe what you see in the images.")
#         else:
#             # Just mention images are available
#             summaries = []
#             for artifact in image_artifacts:
#                 summary = self._extract_image_summary_from_artifact(artifact)
#                 if summary and summary != "Image available in conversation":
#                     # Truncate long summaries for context
#                     if len(summary) > 100:
#                         summary = summary[:100] + "..."
#                     summaries.append(summary)
            
#             if summaries:
#                 image_context_parts.append(f"📋 Context: {len(summaries)} image(s) available - " + " | ".join(summaries))
        
#         # Combine original message with image context
#         if image_context_parts:
#             enhanced_text = "\n".join(image_context_parts + ["", f"User request: {original_text}"])
#         else:
#             enhanced_text = original_text
        
#         # Create new message parts
#         enhanced_parts = [TextPart(type="text", text=enhanced_text)]
        
#         # Create enhanced message
#         enhanced_message = Message(
#             role=original_message.role,
#             parts=enhanced_parts,
#             metadata=original_message.metadata
#         )
        
#         logger.info(f"DEBUG: Enhanced message with {len(image_artifacts)} image contexts")
#         logger.info(f"DEBUG: Enhanced text preview: {enhanced_text[:200]}...")
#         return enhanced_message
    
#     def _extract_image_summary_from_artifact(self, artifact: Artifact) -> str:
#         """Extract image summary from artifact."""
#         summaries = []
        
#         for part in artifact.parts:
#             if hasattr(part, 'text') and part.text:
#                 text = part.text.strip()
#                 # Look for summary lines and clean them up
#                 if text.startswith("Image Summary:"):
#                     # Remove the prefix and add the content
#                     summary_content = text[len("Image Summary:"):].strip()
#                     if summary_content:
#                         summaries.append(summary_content)
#                 elif "Summary:" in text:
#                     summaries.append(text)
#                 elif text and len(text) > 20:  # Any substantial text content
#                     summaries.append(text)
        
#         if summaries:
#             # Join all summaries and ensure it's informative
#             full_summary = " ".join(summaries)
#             # Remove any redundant "Image Summary:" prefixes
#             full_summary = full_summary.replace("Image Summary:", "").strip()
#             return full_summary
        
#         return "Image available in conversation"
    
#     def _extract_user_content(self, message: Message) -> str:
#         """Extract text content from user message."""
#         if not message.parts:
#             return str(message)
        
#         text_parts = []
#         for part in message.parts:
#             if hasattr(part, "type") and part.type == "text":
#                 if hasattr(part, "text"):
#                     text_parts.append(part.text)
#                 elif hasattr(part, "model_dump"):
#                     try:
#                         part_dict = part.model_dump()
#                         if "text" in part_dict:
#                             text_parts.append(part_dict["text"])
#                     except Exception:
#                         pass
        
#         return " ".join(text_parts) if text_parts else str(message)
    
#     def _extract_artifact_content(self, artifact: Artifact) -> str:
#         """Extract text content from artifact."""
#         if not artifact.parts:
#             return ""
        
#         content_parts = []
#         for part in artifact.parts:
#             content = None
            
#             # Method 1: Direct text attribute
#             if hasattr(part, "text"):
#                 content = part.text
            
#             # Method 2: Model dump
#             if not content and hasattr(part, "model_dump"):
#                 try:
#                     part_dict = part.model_dump()
#                     content = part_dict.get("text", "")
#                 except Exception:
#                     pass
            
#             # Method 3: String representation
#             if not content:
#                 content = str(part)
            
#             if content:
#                 content_parts.append(content)
        
#         return " ".join(content_parts)

#     def _looks_like_tool_response(self, content: str) -> bool:
#         """Check if content looks like a tool response that might contain images."""
#         if not content:
#             return False
        
#         # Look for JSON responses or common tool response patterns
#         try:
#             data = json.loads(content)
#             # Check for common image-related fields
#             image_fields = ['image', 'image_data', 'base64', 'screenshot', 'photo', 'picture']
#             return any(field in str(data).lower() for field in image_fields)
            
#         except json.JSONDecodeError:
#             # Look for base64 or image-related keywords in text
#             keywords = ['base64', 'image', 'screenshot', 'photo', 'picture', 'jpeg', 'png']
#             return any(kw in content.lower() for kw in keywords)
    
#     async def _process_tool_images(
#         self, 
#         task_id: str, 
#         session_id: str, 
#         tool_responses: List[str]
#     ) -> List[TaskArtifactUpdateEvent]:
#         """Process tool responses for images and return artifact events."""
#         if not self.image_manager:
#             return []
        
#         artifact_events = []
        
#         for i, response in enumerate(tool_responses):
#             try:
#                 # Try to determine tool name from response context
#                 tool_name = f"tool_{i}"
                
#                 # Try to parse JSON to get better tool name
#                 try:
#                     data = json.loads(response)
#                     if 'diagram_type' in data:
#                         tool_name = f"create_diagram_{data['diagram_type']}"
#                     elif 'chart_type' in data:
#                         tool_name = f"create_chart_{data['chart_type']}"
#                     elif 'target' in data:
#                         tool_name = f"take_screenshot_{data['target']}"
#                 except json.JSONDecodeError:
#                     pass
                
#                 # Process the response for images
#                 image_artifact = await self.image_manager.process_tool_response(
#                     session_id, tool_name, response
#                 )
                
#                 if image_artifact:
#                     # Create the artifact event
#                     artifact = image_artifact.to_artifact(include_full_image=False)
#                     event = TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
#                     artifact_events.append(event)
                    
#                     logger.info(f"Added image {image_artifact.id} to session {session_id}")
            
#             except Exception as e:
#                 logger.error(f"Error processing tool response for images: {e}")
        
#         return artifact_events
    
#     async def cancel_task(self, task_id: str) -> bool:
#         return False
    
#     def get_image_stats(self, session_id: Optional[str] = None) -> Dict[str, Any]:
#         if not self.image_manager:
#             return {"image_management": "disabled"}
#         return self.image_manager.get_image_stats(session_id)
    
#     async def cleanup_session_images(self, session_id: str) -> None:
#         if self.image_manager:
#             self.image_manager.cleanup_session(session_id)