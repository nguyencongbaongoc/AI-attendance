"""
Phase 8.1 — Correlation ID Middleware for Request Tracing.

Generates/propagates correlation IDs for request tracing across the system.
"""

from __future__ import annotations

import re
import uuid
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import structlog.contextvars


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Middleware to generate/propagate correlation IDs."""
    
    # Header names
    REQUEST_HEADER = "X-Request-ID"
    RESPONSE_HEADER = "X-Request-ID"
    
    # Validation
    UUID4_PATTERN = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    MAX_LENGTH = 64
    
    def __init__(self, app, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.header_name = header_name
        self.response_header = header_name
    
    def _generate_id(self) -> str:
        """Generate a new correlation ID."""
        return str(uuid.uuid4())
    
    def _validate_id(self, value: str) -> bool:
        """Validate correlation ID format."""
        if not value or len(value) > self.MAX_LENGTH:
            return False
        # Accept UUID4 or safe alphanumeric with hyphens
        return bool(self.UUID4_PATTERN.match(value)) or bool(
            re.match(r'^[a-zA-Z0-9\-]{1,64}$', value)
        )
    
    def _extract_id(self, request: Request) -> Optional[str]:
        """Extract correlation ID from request headers."""
        # Check standard header
        cid = request.headers.get(self.header_name)
        if cid and self._validate_id(cid):
            return cid
        
        # Check alternative headers (for compatibility)
        for alt_header in ["X-Correlation-ID", "X-Trace-ID", "Request-ID"]:
            cid = request.headers.get(alt_header)
            if cid and self._validate_id(cid):
                return cid
        
        return None
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract or generate correlation ID
        correlation_id = self._extract_id(request)
        if not correlation_id:
            correlation_id = self._generate_id()
        
        # Bind to structlog context for this request
        token = structlog.contextvars.bind_contextvars(request_id=correlation_id)
        
        try:
            # Process request
            response = await call_next(request)
            
            # Add correlation ID to response headers
            response.headers[self.response_header] = correlation_id
            
            return response
            
        finally:
            # Unbind context
            structlog.contextvars.unbind_contextvars(token)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from structlog context."""
    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("request_id")


_get_correlation_id = get_correlation_id


def set_correlation_id(correlation_id: str):
    """Set the correlation ID in structlog context (for WebSocket/SSE)."""
    structlog.contextvars.bind_contextvars(request_id=correlation_id)


def clear_correlation_id():
    """Clear the correlation ID from structlog context."""
    structlog.contextvars.unbind_contextvars("request_id")