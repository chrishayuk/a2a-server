# a2a_server/middleware/auth.py
from __future__ import annotations

import re
import logging
from typing import Optional, Set, Callable, Awaitable

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """
    Bearer token authentication middleware for A2A server.
    
    Similar to MCP server auth but adapted for A2A server endpoints.
    If bearer_token is set in config, requires authentication.
    If not set, allows all requests (open mode).
    """
    
    def __init__(
        self, 
        app: ASGIApp, 
        bearer_token: Optional[str] = None,
        health_paths: Optional[Set[str]] = None,
        exclude_paths: Optional[Set[str]] = None
    ) -> None:
        """
        Initialize bearer token authentication middleware.
        
        Args:
            app: ASGI application
            bearer_token: Required bearer token (if None, auth is disabled)
            health_paths: Paths that bypass auth (e.g., /health, /ready)
            exclude_paths: Additional paths to exclude from auth
        """
        super().__init__(app)
        self.bearer_token = bearer_token
        self.health_paths = health_paths or {"/health", "/ready", "/metrics"}
        self.exclude_paths = exclude_paths or set()
        
        # Combine all excluded paths
        self.excluded_paths = self.health_paths | self.exclude_paths
        
        # Log auth status
        if self.bearer_token:
            logger.info("🔐 Bearer token authentication ENABLED")
            logger.info(f"🔐 Excluded paths: {sorted(self.excluded_paths)}")
        else:
            logger.info("🔓 Bearer token authentication DISABLED (open mode)")
    
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request with bearer token authentication."""
        
        # Skip auth if no token configured (open mode)
        if not self.bearer_token:
            return await call_next(request)
        
        # Skip auth for excluded paths
        if self._is_excluded_path(request.url.path, request.method):
            return await call_next(request)
        
        # Extract token from request
        token = self._extract_token(request)
        
        if not token:
            logger.warning(f"🔐 Missing bearer token for {request.method} {request.url.path}")
            return JSONResponse(
                {"error": "Authentication required", "detail": "Missing bearer token"}, 
                status_code=401
            )
        
        # Validate token
        if not self._validate_token(token):
            logger.warning(f"🔐 Invalid bearer token for {request.method} {request.url.path}")
            return JSONResponse(
                {"error": "Authentication failed", "detail": "Invalid bearer token"}, 
                status_code=401
            )
        
        # Token is valid, add user info to request scope
        request.scope["authenticated"] = True
        request.scope["auth_method"] = "bearer_token"
        
        logger.debug(f"🔐 Authenticated request: {request.method} {request.url.path}")
        
        return await call_next(request)
    
    def _is_excluded_path(self, path: str, method: str) -> bool:
        """Check if path should be excluded from authentication."""
        # Exact path matches
        if path in self.excluded_paths:
            return True
        
        # Health endpoints are always excluded for GET requests
        if method == "GET" and path in self.health_paths:
            return True
        
        # Pattern-based exclusions (you can extend this)
        excluded_patterns = [
            r"^/health$",
            r"^/ready$", 
            r"^/metrics$",
            r"^/.well-known/.*",  # Well-known endpoints
            r"^/docs$",           # API docs (if enabled)
            r"^/redoc$",          # ReDoc (if enabled)
            r"^/openapi.json$"    # OpenAPI spec (if enabled)
        ]
        
        for pattern in excluded_patterns:
            if re.match(pattern, path):
                return True
        
        return False
    
    def _extract_token(self, request: Request) -> Optional[str]:
        """Extract bearer token from request headers or cookies."""
        token = None
        
        # 1) Authorization header (primary method)
        auth_header = request.headers.get("Authorization", "")
        if auth_header:
            match = re.match(r"Bearer\s+(.+)", auth_header, re.IGNORECASE)
            if match:
                token = match.group(1)
        
        # 2) Cookie fallback (for browser clients)
        if not token:
            token = request.cookies.get("auth_token") or request.cookies.get("bearer_token")
        
        # 3) Query parameter fallback (for testing/debugging - not recommended for production)
        if not token and logger.isEnabledFor(logging.DEBUG):
            token = request.query_params.get("token")
            if token:
                logger.debug("🔐 Using token from query parameter (debug mode only)")
        
        return token
    
    def _validate_token(self, token: str) -> bool:
        """Validate the provided token."""
        if not token or not self.bearer_token:
            return False
        
        # Simple constant-time comparison to prevent timing attacks
        return self._secure_compare(token, self.bearer_token)
    
    def _secure_compare(self, a: str, b: str) -> bool:
        """Constant-time string comparison to prevent timing attacks."""
        if len(a) != len(b):
            return False
        
        result = 0
        for x, y in zip(a, b):
            result |= ord(x) ^ ord(y)
        
        return result == 0


def create_auth_middleware(bearer_token: Optional[str] = None, **kwargs) -> BearerTokenAuthMiddleware:
    """
    Factory function to create auth middleware with A2A-specific defaults.
    
    Args:
        bearer_token: Bearer token for authentication (None = disabled)
        **kwargs: Additional arguments for BearerTokenAuthMiddleware
        
    Returns:
        Configured authentication middleware
    """
    
    # A2A-specific health and excluded paths
    default_health_paths = {
        "/health",
        "/ready", 
        "/metrics"
    }
    
    default_exclude_paths = {
        "/.well-known/agent.json",  # Agent card endpoint
        "/agent-card.json",         # Root agent card
        "/agent-cards"              # Agent cards collection
    }
    
    # Merge with user-provided paths
    health_paths = kwargs.get("health_paths", set()) | default_health_paths
    exclude_paths = kwargs.get("exclude_paths", set()) | default_exclude_paths
    
    kwargs["health_paths"] = health_paths
    kwargs["exclude_paths"] = exclude_paths
    
    def middleware_factory(app: ASGIApp) -> BearerTokenAuthMiddleware:
        return BearerTokenAuthMiddleware(app, bearer_token, **kwargs)
    
    return middleware_factory


# Updated config integration
def configure_auth_from_config(config: dict) -> Optional[Callable]:
    """
    Configure authentication middleware from A2A server configuration.
    
    Args:
        config: Server configuration dictionary
        
    Returns:
        Middleware factory function or None if auth disabled
    """
    auth_config = config.get("auth", {})
    
    # Check if bearer token auth is enabled
    bearer_token = auth_config.get("bearer_token")
    if not bearer_token:
        logger.info("🔓 Bearer token authentication disabled in configuration")
        return None
    
    # Additional configuration options
    health_paths = set(auth_config.get("health_paths", []))
    exclude_paths = set(auth_config.get("exclude_paths", []))
    
    logger.info("🔐 Configuring bearer token authentication from config")
    logger.info(f"🔐 Token configured: {'Yes' if bearer_token else 'No'}")
    
    return create_auth_middleware(
        bearer_token=bearer_token,
        health_paths=health_paths,
        exclude_paths=exclude_paths
    )


# Usage example and testing utilities
async def validate_token_async(token: str) -> dict:
    """
    Async token validation function (for future extensions).
    
    This can be extended to validate JWT tokens, check against databases, etc.
    
    Args:
        token: Bearer token to validate
        
    Returns:
        User/payload information if valid
        
    Raises:
        HTTPException: If token is invalid
    """
    # For now, this is just a placeholder
    # In the future, you could:
    # - Decode JWT tokens
    # - Check against a user database
    # - Validate with external auth service
    
    if not token:
        raise HTTPException(status_code=401, detail="Token required")
    
    # Placeholder validation
    # Replace with actual validation logic
    return {
        "authenticated": True,
        "method": "bearer_token",
        "token_type": "static"  # Could be "jwt", "api_key", etc.
    }


def create_test_client_with_auth(app, bearer_token: str):
    """
    Helper to create a test client with authentication headers.
    
    Useful for testing authenticated endpoints.
    """
    from fastapi.testclient import TestClient
    
    class AuthenticatedTestClient(TestClient):
        def __init__(self, app, token: str):
            super().__init__(app)
            self.token = token
        
        def request(self, method, url, **kwargs):
            # Add auth header to all requests
            headers = kwargs.get("headers", {})
            headers["Authorization"] = f"Bearer {self.token}"
            kwargs["headers"] = headers
            
            return super().request(method, url, **kwargs)
    
    return AuthenticatedTestClient(app, bearer_token)


__all__ = [
    "BearerTokenAuthMiddleware",
    "create_auth_middleware", 
    "configure_auth_from_config",
    "validate_token_async",
    "create_test_client_with_auth"
]