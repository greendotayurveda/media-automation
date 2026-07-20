"""
Async database connection and session management.
Uses SQLAlchemy 2.x async engine with connection pooling.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.config.settings import settings
from shared.logging.logger import get_logger

logger = get_logger(__name__)


def create_engine() -> AsyncEngine:
    """Create the async SQLAlchemy engine."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
        pool_timeout=settings.postgres_pool_timeout,
        pool_pre_ping=True,          # verify connection health before use
        pool_recycle=3600,           # recycle connections every 1 hour
        echo=settings.env == "development",
    )


engine: AsyncEngine = create_engine()

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions.

    Usage:
        async with get_db_session() as db:
            result = await db.execute(select(Movie))
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Usage:
        @router.get("/movies")
        async def list_movies(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connection() -> bool:
    """Health check — verify database connectivity."""
    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database health check failed", error=str(exc))
        return False


async def close_db_connection() -> None:
    """Gracefully close the database connection pool."""
    await engine.dispose()
    logger.info("Database connection pool closed")
