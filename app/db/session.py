"""
Database session management with MySQL/SQLAlchemy and SQLite fallback.
"""

from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


def get_database_url() -> tuple[str, str]:
    """
    Get database URL and driver type.
    
    Returns:
        Tuple of (database_url, driver_type) where driver_type is 'mysql' or 'sqlite'
    """
    mysql_host = os.getenv("MYSQL_HOST")
    mysql_port = os.getenv("MYSQL_PORT", "3306")
    mysql_user = os.getenv("MYSQL_USER")
    mysql_password = os.getenv("MYSQL_PASSWORD")
    mysql_db = os.getenv("MYSQL_DB")
    
    if mysql_host and mysql_user and mysql_password and mysql_db:
        url = f"mysql+aiomysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}?charset=utf8mb4"
        return url, "mysql"
    
    # Fallback to SQLite
    sqlite_path = os.getenv("SQLITE_SCHOOL_DB", "app/data/school.db")
    url = f"sqlite+aiosqlite:///{sqlite_path}"
    return url, "sqlite"


async def init_database() -> None:
    """Initialize database engine and session factory with MySQL/SQLite fallback."""
    global _engine, _session_factory
    
    if _engine is not None:
        return
    
    url, driver = get_database_url()
    
    if driver == "mysql":
        logger.info("Attempting MySQL connection...")
        try:
            _engine = create_async_engine(
                url,
                echo=False,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                pool_recycle=3600,
            )
            # Test connection
            async with _engine.begin() as conn:
                await conn.execute("SELECT 1")
            logger.info("MySQL connection successful")
        except Exception as e:
            logger.warning(f"MySQL connection failed: {e}. Falling back to SQLite.")
            _engine = None
    
    if _engine is None:
        # Use SQLite fallback
        url, _ = get_database_url()
        logger.info(f"Using SQLite database: {url}")
        _engine = create_async_engine(
            url,
            echo=False,
            poolclass=NullPool,
        )
    
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_database() -> None:
    """Close database engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session with automatic commit/rollback.
    
    Usage:
        async with get_db_session() as session:
            # use session
            pass
    """
    if _session_factory is None:
        await init_database()
    
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_session_factory() -> async_sessionmaker:
    """Get the session factory (for dependency injection)."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _session_factory


async def create_tables() -> None:
    """Create all tables (for development/testing)."""
    from app.models.student import Base
    
    if _engine is None:
        await init_database()
    
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database tables created/verified")