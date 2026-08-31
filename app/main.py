"""
Phase 37C — FastAPI Application for Health Monitoring and Operational API.

Main entry point for the REST API server.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.websocket import router as websocket_router
from app.api.attendance import router as attendance_router
from app.api.persons import router as persons_router
from app.api.timetable import router as timetable_router
from app.api.excel import router as excel_router
from app.api.parent_telegram import router as parent_telegram_router
from app.api.geometry import router as geometry_router
from app.bootstrap.port_discovery import find_backend_port
from app.config.settings import load_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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

    # CORS middleware for frontend integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers - manually add routes due to FastAPI version issue
    for router in [health_router, websocket_router, attendance_router, persons_router, timetable_router, excel_router, parent_telegram_router, geometry_router]:
        for route in router.routes:
            app.router.routes.append(route)

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
        """Readiness probe."""
        settings = load_settings()
        # Check critical components
        import os
        checks = {
            "data_dir": os.path.exists(settings.paths.data_dir),
            "models_dir": os.path.exists(settings.paths.models_dir),
            "parent_registry_db": os.path.exists(settings.parent_registry.db_path),
            "notification_queue_db": os.path.exists(settings.notification_queue.db_path),
        }

        all_ready = all(checks.values())
        return {
            "status": "ready" if all_ready else "not_ready",
            "checks": checks,
        }

    return app


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
    )