"""
Phase 37C + Phase 7 — FastAPI Application with Security Hardening.

Main entry point for the REST API server.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable

from fastapi import FastAPI, Request, Response, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.middleware.correlation_id import CorrelationIDMiddleware, get_correlation_id as _get_correlation_id

from app.api.health import router as health_router
from app.api.websocket import router as websocket_router
from app.api.attendance import router as attendance_router
from app.api.attendance_ws import router as attendance_ws_router
from app.api.persons import router as persons_router
from app.api.timetable import router as timetable_router
from app.api.excel import router as excel_router
from app.api.parent_telegram import router as parent_telegram_router
from app.api.geometry import router as geometry_router
from app.api.enrollment import router as enrollment_router
from app.api.ai_worker import router as ai_worker_router
from app.api.replay import router as replay_router
from app.api.provenance import router as provenance_router
from app.api.metadata_stream import router as metadata_stream_router
from app.api.routes_students import router as students_router
from app.bootstrap.port_discovery import find_backend_port
from app.config.settings import load_settings
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiting Middleware (Token Bucket)
# =============================================================================

class TokenBucket:
    """Simple token bucket for rate limiting."""
    
    def __init__(self, rate: float, burst: int):
        self.rate = rate  # tokens per second
        self.burst = burst  # max tokens
        self.tokens = float(burst)
        self.last_update = time.monotonic()
    
    def consume(self, tokens: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_update = now
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiting middleware."""
    
    def __init__(self, app: FastAPI, settings):
        super().__init__(app)
        self.settings = settings
        self.buckets: dict[str, TokenBucket] = {}
        self.auth_paths = {"/api/v1/health/ai-worker", "/api/v1/attendance/events", "/api/v1/ai/control"}
        self.ws_paths = {"/api/v1/attendance/ws", "/api/v1/health/ws"}
    
    def _get_client_key(self, request: Request) -> str:
        # Use X-Forwarded-For if behind proxy, else client host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        return f"{client_ip}:{request.url.path}"
    
    def _get_bucket_config(self, path: str) -> tuple[float, int]:
        """Get rate limit config for a path."""
        rl_config = self.settings.rate_limit
        
        # Check if auth endpoint
        if any(path.startswith(auth_path) for auth_path in self.auth_paths):
            return (rl_config.auth_rpm / 60.0, rl_config.auth_burst)
        
        # Check if WebSocket endpoint
        if any(path.startswith(ws_path) for ws_path in self.ws_paths):
            return (rl_config.ws_connections_per_minute / 60.0, rl_config.ws_burst)
        
        # Default
        return (rl_config.default_rpm / 60.0, rl_config.default_burst)
    
    def _get_or_create_bucket(self, key: str, rate: float, burst: int) -> TokenBucket:
        if key not in self.buckets:
            self.buckets[key] = TokenBucket(rate, burst)
        return self.buckets[key]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting if disabled
        if not self.settings.security.rate_limit_enabled:
            return await call_next(request)
        
        # Skip for health liveness/readiness (infrastructure endpoints)
        if request.url.path in ("/api/v1/health/live", "/api/v1/health/ready"):
            return await call_next(request)
        
        client_key = self._get_client_key(request)
        rate, burst = self._get_bucket_config(request.url.path)
        bucket = self._get_or_create_bucket(client_key, rate, burst)
        
        if not bucket.consume():
            # Rate limited - log structured failure
            from app.logging.logger import get_logger, log_failure
            from app.middleware.correlation_id import _get_correlation_id
            rl_logger = get_logger("app.security.rate_limit")
            log_failure(
                rl_logger, "Rate limit exceeded", "rate_limit", "check_limit",
                "RateLimitExceeded", "rate_limit_exceeded",
                retry_state="none",
                correlation_id=_get_correlation_id(),
                client_key=client_key,
                path=request.url.path,
                method=request.method,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Please slow down."},
                headers={"Retry-After": "60"},
            )
        
        return await call_next(request)


# =============================================================================
# Request Size Limit Middleware
# =============================================================================

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Limit request body size."""
    
    def __init__(self, app: FastAPI, max_size_bytes: int):
        super().__init__(app)
        self.max_size_bytes = max_size_bytes
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check Content-Length header
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > self.max_size_bytes:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": f"Request body too large. Maximum size: {self.max_size_bytes} bytes"},
                    )
            except ValueError:
                pass
        
        # For streaming bodies, we'd need to read and check, but Content-Length check is usually sufficient
        return await call_next(request)


# =============================================================================
# Request Timeout Middleware
# =============================================================================

class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Add request timeout."""
    
    def __init__(self, app: FastAPI, timeout_seconds: int):
        super().__init__(app)
        self.timeout_seconds = timeout_seconds
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Note: True timeout requires asyncio.wait_for which can cancel the request
        # For now, we rely on uvicorn's timeout settings
        # This middleware adds the timeout header for documentation
        response = await call_next(request)
        response.headers["X-Request-Timeout"] = str(self.timeout_seconds)
        return response


# =============================================================================
# Request Timing Middleware (Observability)
# =============================================================================

class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log request timing for observability."""
    
    def __init__(self, app: FastAPI):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        import time
        start = time.perf_counter()
        
        response = await call_next(request)
        
        duration_ms = (time.perf_counter() - start) * 1000
        
        # Log request completion
        from app.logging.logger import get_logger
        logger = get_logger("app.http")
        logger.info(
            "HTTP request completed",
            component="http",
            action="request",
            result="success" if response.status_code < 400 else "failure",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            correlation_id=_get_correlation_id(),
        )
        
        # Add timing header
        response.headers["X-Response-Time-ms"] = str(round(duration_ms, 2))
        
        return response


# =============================================================================
# Security Headers Middleware
# =============================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to responses."""
    
    def __init__(self, app: FastAPI, settings):
        super().__init__(app)
        self.settings = settings
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        if not self.settings.security.security_headers_enabled:
            return response
        
        sec = self.settings.security
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = sec.content_security_policy
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = sec.referrer_policy
        
        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = sec.x_content_type_options
        
        # X-Frame-Options
        response.headers["X-Frame-Options"] = sec.x_frame_options
        
        # Remove server header (using __delitem__ for MutableHeaders)
        if "Server" in response.headers:
            del response.headers["Server"]
        
        return response


# =============================================================================
# API Key Cache for Rotation Support
# =============================================================================

from app.security.api_key_cache import get_api_key_cache, init_api_key_cache


# =============================================================================
# Application Factory
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    logger.info("Starting AI Attendance System API...")

    # Load settings to validate configuration
    settings = load_settings()
    settings.ensure_directories()

    logger.info("Configuration loaded and directories ensured")
    logger.info(f"Data directory: {settings.paths.data_dir}")
    logger.info(f"Models directory: {settings.paths.models_dir}")
    logger.info(f"Logs directory: {settings.paths.logs_dir}")

    yield

    logger.info("Shutting down AI Attendance System API...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = load_settings()

    app = FastAPI(
        title="AI Attendance System API",
        description="Health monitoring and operational API for AI Attendance System",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Correlation ID middleware - FIRST to capture all requests
    app.add_middleware(CorrelationIDMiddleware)

    # Request timing middleware - SECOND to capture all request durations
    app.add_middleware(RequestTimingMiddleware)

    # CORS middleware - restrict to configured origins
    cors_config = settings.security
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_config.cors_allowed_origins,
        allow_credentials=cors_config.cors_allow_credentials,
        allow_methods=cors_config.cors_allowed_methods,
        allow_headers=cors_config.cors_allowed_headers,
    )

    # Security headers middleware (order matters - should be early)
    if cors_config.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    # Request size limit middleware
    max_size = cors_config.max_request_size_mb * 1024 * 1024
    app.add_middleware(RequestSizeLimitMiddleware, max_size_bytes=max_size)

    # Request timeout middleware
    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=cors_config.request_timeout_seconds)

    # Rate limiting middleware (after size/timeout, before routes)
    if cors_config.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware, settings=settings)

    # Include routers - manually add routes due to FastAPI version issue
    for router in [
        health_router, websocket_router, attendance_router, attendance_ws_router,
        persons_router, timetable_router, excel_router, parent_telegram_router,
        geometry_router, enrollment_router, ai_worker_router, replay_router, provenance_router,
        metadata_stream_router, students_router
    ]:
        for route in router.routes:
            app.router.routes.append(route)

    # Mount /recordings/* as a static directory for Replay
    recordings_path = Path(settings.paths.recordings_dir)
    recordings_path.mkdir(parents=True, exist_ok=True)
    app.mount("/recordings", StaticFiles(directory=str(recordings_path), check_dir=False), name="recordings")
    
    # Mount /static/evidence/* for evidence snapshots and clips
    evidence_path = Path("app/static/evidence")
    evidence_path.mkdir(parents=True, exist_ok=True)
    app.mount("/static/evidence", StaticFiles(directory=str(evidence_path), check_dir=False), name="evidence")

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "service": "AI Attendance System API",
            "version": "1.0.0",
            "status": "running",
            "docs": "/docs",
            "health": "/api/v1/health/system",
        }

    @app.get("/api/v1/health/live")
    async def liveness():
        """Liveness probe."""
        return {"status": "alive"}

    @app.get("/api/v1/health/ready")
    async def readiness():
        """Enhanced readiness probe with dependency checks."""
        settings = load_settings()
        import os
        import sqlite3
        
        checks = {
            "data_dir": os.path.exists(settings.paths.data_dir),
            "models_dir": os.path.exists(settings.paths.models_dir),
            "parent_registry_db": os.path.exists(settings.parent_registry.db_path),
            "notification_queue_db": os.path.exists(settings.notification_queue.db_path),
        }
        
        # Database connectivity checks
        for db_name, db_path in [
            ("parent_registry", settings.parent_registry.db_path),
            ("notification_queue", settings.notification_queue.db_path),
            ("exit_sessions", settings.exit_session.db_path),
        ]:
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                conn.execute("SELECT 1").fetchone()
                conn.close()
                checks[f"{db_name}_db_connectivity"] = True
            except Exception as e:
                logger.warning(f"Database connectivity check failed for {db_name}: {e}")
                checks[f"{db_name}_db_connectivity"] = False
        
        # MediaMTX API check (optional - don't fail if not running)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"http://localhost:{settings.cameras.mediamtx_api_port}/api/paths")
                checks["mediamtx_api"] = resp.status_code == 200
        except Exception:
            checks["mediamtx_api"] = False  # Non-critical for readiness
        
        # GPU availability check
        try:
            import torch
            checks["gpu_cuda"] = torch.cuda.is_available()
        except Exception:
            checks["gpu_cuda"] = False
        
        # Worker health check (check if any worker reported recently)
        from app.api.ai_worker import _worker_health_states, _check_stale_workers
        _check_stale_workers(30.0)
        has_healthy_worker = any(
            s.health_status == "healthy" for s in _worker_health_states.values()
        )
        checks["worker_healthy"] = has_healthy_worker
        
        all_ready = all(checks.values())
        return {
            "status": "ready" if all_ready else "not_ready",
            "checks": checks,
        }

    # API Key rotation endpoint (admin only)
    @app.post("/api/v1/admin/security/rotate-keys")
    async def rotate_api_keys(request: Request, x_api_key: str = Header(..., alias="X-API-Key")):
        """Rotate API keys - invalidate cache to force reload from environment."""
        # Verify admin key using cache (supports rotation)
        cache = get_api_key_cache()
        expected = cache.get("ADMIN_API_KEY")
        if not expected or not secrets.compare_digest(x_api_key, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Admin API key")
        
        cache.invalidate_all()
        
        logger.info("API key cache invalidated - keys will be reloaded from environment on next request")
        return {"success": True, "message": "API key cache cleared. Keys will be reloaded from environment."}

    return app


# Initialize the API key cache with settings on startup
def _init_api_key_cache_on_startup():
    """Initialize API key cache with settings TTL."""
    settings = load_settings()
    init_api_key_cache(settings.security.api_key_cache_ttl_seconds)

# Call initialization
_init_api_key_cache_on_startup()

app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = load_settings()
    
    # Use dynamic port discovery for backend
    backend_port = find_backend_port()
    logger.info(f"Starting backend on dynamic port: {backend_port}")
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=backend_port,
        reload=settings.runtime.debug,
        log_level=settings.runtime.log_level.lower(),
        # Built-in timeouts
        timeout_keep_alive=settings.security.request_timeout_seconds,
        limit_max_requests=10000,
    )