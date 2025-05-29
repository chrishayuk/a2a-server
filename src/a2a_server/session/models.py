#!/usr/bin/env python3
# a2a_server/session/models.py
"""
Data models for image artifacts and related session objects.

Contains the core data structures used by the image session management system.
"""

import base64
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from a2a_json_rpc.spec import Artifact, TextPart

@dataclass
class ImageArtifact:
    """Represents an image artifact with metadata and summary."""
    
    image_data: str
    source: str = "tool_call"
    format: str = "base64"
    mime_type: str = "image/jpeg"
    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    # Analysis results (populated after vision analysis)
    summary: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Auto-generated fields
    id: str = field(init=False)
    
    def __post_init__(self):
        """Generate unique ID after initialization."""
        self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate unique ID from image content hash."""
        hasher = hashlib.sha256()
        hasher.update(self.image_data.encode())
        return f"img_{hasher.hexdigest()[:12]}"
    
    def update_analysis(
        self, 
        summary: str, 
        tags: Optional[List[str]] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update the analysis results for this image."""
        self.summary = summary
        if tags:
            self.tags = tags
        if metadata:
            self.metadata.update(metadata)
    
    def to_artifact(self, include_full_image: bool = False) -> Artifact:
        """Convert to A2A Artifact."""
        parts = []
        
        # Always include summary if available
        if self.summary:
            parts.append(TextPart(
                type="text",
                text=f"Image Summary: {self.summary}"
            ))
        
        # Include tags and metadata
        if self.tags:
            parts.append(TextPart(
                type="text", 
                text=f"Tags: {', '.join(self.tags)}"
            ))
        
        # Include description if available
        if self.description:
            parts.append(TextPart(
                type="text",
                text=f"Source: {self.description}"
            ))
        
        # Conditionally include full image
        if include_full_image:
            try:
                from a2a_json_rpc.spec import ImagePart
                parts.append(ImagePart(
                    type="image",
                    data=self.image_data,
                    format=self.format,
                    mime_type=self.mime_type
                ))
            except ImportError:
                # Fallback if ImagePart doesn't exist
                parts.append(TextPart(
                    type="text",
                    text=f"[Image: {self.mime_type}, {len(self.image_data)} chars base64 data]"
                ))
        
        return Artifact(
            name=f"image_{self.id}",
            parts=parts,
            index=0,
            metadata={
                "image_id": self.id,
                "source": self.source,
                "created_at": self.created_at.isoformat(),
                "has_full_image": include_full_image,
                "image_format": self.format,
                "mime_type": self.mime_type,
                **self.metadata
            }
        )
    
    def to_vision_content(self) -> Dict[str, Any]:
        """Convert to vision model content format."""
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{self.mime_type};base64,{self.image_data}"
            }
        }
    
    def get_size_estimate(self) -> Dict[str, Any]:
        """Get size estimates for the image."""
        base64_size = len(self.image_data)
        estimated_bytes = base64_size * 0.75  # Base64 is ~33% larger than binary
        
        return {
            "base64_chars": base64_size,
            "estimated_bytes": int(estimated_bytes),
            "estimated_mb": estimated_bytes / (1024 * 1024),
            "estimated_tokens": base64_size // 4  # Rough token estimate
        }
    
    def is_valid_image(self) -> bool:
        """Check if the image data appears to be valid."""
        if not self.image_data or len(self.image_data) < 100:
            return False
            
        try:
            # Try to decode
            decoded = base64.b64decode(self.image_data)
            
            # Check for common image headers
            image_headers = [
                b'\xff\xd8\xff',  # JPEG
                b'\x89PNG\r\n\x1a\n',  # PNG
                b'GIF87a',  # GIF87a
                b'GIF89a',  # GIF89a
                b'RIFF',  # WebP (starts with RIFF)
            ]
            
            return any(decoded.startswith(header) for header in image_headers)
            
        except Exception:
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "source": self.source,
            "format": self.format,
            "mime_type": self.mime_type,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "summary": self.summary,
            "tags": self.tags,
            "metadata": self.metadata,
            "size_info": self.get_size_estimate(),
            "valid": self.is_valid_image()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], image_data: str) -> 'ImageArtifact':
        """Create ImageArtifact from dictionary representation."""
        artifact = cls(
            image_data=image_data,
            source=data.get("source", "unknown"),
            format=data.get("format", "base64"),
            mime_type=data.get("mime_type", "image/jpeg"),
            description=data.get("description"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()
        )
        
        # Update analysis data
        if "summary" in data:
            artifact.summary = data["summary"]
        if "tags" in data:
            artifact.tags = data["tags"]
        if "metadata" in data:
            artifact.metadata = data["metadata"]
        
        return artifact

@dataclass
class ImageSessionMetadata:
    """Metadata about images in a session."""
    
    session_id: str
    image_ids: List[str] = field(default_factory=list)
    last_image_query: Optional[datetime] = None
    total_images: int = 0
    total_size_mb: float = 0.0
    
    def add_image(self, image_id: str, size_mb: float) -> None:
        """Add an image to this session's metadata."""
        if image_id not in self.image_ids:
            self.image_ids.append(image_id)
            self.total_images += 1
            self.total_size_mb += size_mb
    
    def remove_image(self, image_id: str, size_mb: float) -> None:
        """Remove an image from this session's metadata."""
        if image_id in self.image_ids:
            self.image_ids.remove(image_id)
            self.total_images -= 1
            self.total_size_mb = max(0, self.total_size_mb - size_mb)
    
    def mark_image_query(self) -> None:
        """Mark that an image-related query was made."""
        self.last_image_query = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "session_id": self.session_id,
            "image_ids": self.image_ids,
            "last_image_query": self.last_image_query.isoformat() if self.last_image_query else None,
            "total_images": self.total_images,
            "total_size_mb": self.total_size_mb
        }

@dataclass 
class ImageAnalysisRequest:
    """Request for image analysis."""
    
    image_artifact: ImageArtifact
    analysis_type: str = "summary"  # summary, detailed, tags, etc.
    custom_prompt: Optional[str] = None
    max_tokens: int = 150
    
    def to_vision_messages(self) -> List[Dict[str, Any]]:
        """Convert to messages for vision model."""
        if self.custom_prompt:
            text_prompt = self.custom_prompt
        else:
            text_prompt = self._get_default_prompt()
        
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    self.image_artifact.to_vision_content()
                ]
            }
        ]
    
    def _get_default_prompt(self) -> str:
        """Get default prompt based on analysis type."""
        prompts = {
            "summary": "Analyze this image and provide: 1) A concise 1-2 sentence description, 2) 3-5 relevant tags, 3) Any text or important details visible. Be brief but informative.",
            "detailed": "Provide a detailed analysis of this image including all visible elements, text, colors, composition, and any notable features.",
            "tags": "List 5-10 descriptive tags for this image, focusing on the main subjects, objects, and characteristics.",
            "text": "Extract and transcribe any text visible in this image.",
            "objects": "Identify and list all objects, people, and elements visible in this image."
        }
        
        return prompts.get(self.analysis_type, prompts["summary"])

@dataclass
class ImageAnalysisResult:
    """Result of image analysis."""
    
    image_id: str
    analysis_type: str
    summary: str
    tags: List[str] = field(default_factory=list)
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "image_id": self.image_id,
            "analysis_type": self.analysis_type,
            "summary": self.summary,
            "tags": self.tags,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }

# Utility functions for working with image artifacts

def extract_image_from_tool_response(response: str) -> Optional[str]:
    """Extract base64 image data from tool response."""
    try:
        # Try to parse as JSON first
        data = json.loads(response)
        
        # Look for common image fields
        for field in ['image', 'image_data', 'base64', 'data', 'content']:
            if field in data and isinstance(data[field], str):
                # Validate it looks like base64
                candidate = data[field]
                if is_base64_image(candidate):
                    return candidate
        
        # Look for data URLs
        if 'url' in data and data['url'].startswith('data:image'):
            # Extract base64 part from data URL
            if ',' in data['url']:
                return data['url'].split(',', 1)[1]
                
    except json.JSONDecodeError:
        # Try to find base64 data in raw response
        lines = response.split('\n')
        for line in lines:
            line = line.strip()
            if is_base64_image(line):
                return line
    
    return None

def is_base64_image(data: str) -> bool:
    """Check if string looks like base64 image data."""
    if len(data) < 100:  # Too short to be an image
        return False
        
    try:
        # Try to decode
        decoded = base64.b64decode(data)
        
        # Check for common image headers
        image_headers = [
            b'\xff\xd8\xff',  # JPEG
            b'\x89PNG\r\n\x1a\n',  # PNG
            b'GIF87a',  # GIF87a
            b'GIF89a',  # GIF89a
            b'RIFF',  # WebP (starts with RIFF)
        ]
        
        return any(decoded.startswith(header) for header in image_headers)
        
    except Exception:
        return False

def create_image_artifact_from_tool(
    tool_name: str,
    tool_response: str,
    description: Optional[str] = None
) -> Optional[ImageArtifact]:
    """Create ImageArtifact from tool response."""
    image_data = extract_image_from_tool_response(tool_response)
    if not image_data:
        return None
    
    # Try to determine mime type from tool response
    mime_type = "image/jpeg"  # default
    try:
        data = json.loads(tool_response)
        if 'format' in data:
            format_str = data['format'].lower()
            if format_str in ['png', 'jpeg', 'jpg', 'gif', 'webp']:
                mime_type = f"image/{format_str.replace('jpg', 'jpeg')}"
    except:
        pass
    
    return ImageArtifact(
        image_data=image_data,
        source=f"tool_call:{tool_name}",
        mime_type=mime_type,
        description=description or f"Image returned by {tool_name}"
    )