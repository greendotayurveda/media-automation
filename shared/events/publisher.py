"""
Async Redis event publisher using Redis Streams.
All services use this to publish events onto the platform event bus.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.logging.logger import get_logger

logger = get_logger(__name__)

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get or create the shared Redis connection."""
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection on shutdown."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed")


class EventPublisher:
    """
    Publishes events to Redis Streams.

    Usage:
        publisher = EventPublisher(stream=StreamName.MEDIA)
        await publisher.publish(
            event_type=EventType.MOVIE_RECEIVED,
            payload={"movie_id": "abc123", "path": "/downloads/movie.mkv"},
            source_service="telegram-service",
        )
    """

    def __init__(self, stream: StreamName) -> None:
        self.stream = stream.value

    async def publish(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        source_service: str,
        correlation_id: str | None = None,
        max_stream_length: int = 10_000,
    ) -> str:
        """
        Publish an event to the Redis stream.

        Returns the event ID assigned by Redis.
        """
        redis = await get_redis()

        event_id = str(uuid.uuid4())
        correlation_id = correlation_id or event_id

        message = {
            "event_id": event_id,
            "event_type": event_type.value,
            "correlation_id": correlation_id,
            "source_service": source_service,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "payload": json.dumps(payload),
        }

        redis_id = await redis.xadd(
            self.stream,
            message,
            maxlen=max_stream_length,
            approximate=True,  # ~maxlen for performance
        )

        logger.info(
            "Event published",
            event_type=event_type.value,
            event_id=event_id,
            stream=self.stream,
            source=source_service,
        )

        return redis_id

    async def publish_to_dead_letter(
        self,
        original_event: dict[str, Any],
        error: str,
        retry_count: int,
    ) -> None:
        """Send a failed event to the dead-letter queue."""
        redis = await get_redis()
        await redis.xadd(
            StreamName.DEAD_LETTER.value,
            {
                **original_event,
                "dlq_error": error,
                "dlq_retry_count": str(retry_count),
                "dlq_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            maxlen=5_000,
            approximate=True,
        )
        logger.warning(
            "Event sent to dead-letter queue",
            event_type=original_event.get("event_type"),
            error=error,
            retry_count=retry_count,
        )
