"""
Async Redis Streams event subscriber.
Services extend EventSubscriber to consume events from their assigned stream.
"""
import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

import redis.asyncio as aioredis

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import get_redis, EventPublisher
from shared.logging.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [1, 5, 30]  # exponential-ish backoff


class EventSubscriber(ABC):
    """
    Base class for consuming events from a Redis Stream.

    Subclass this in each service worker:

    Example:
        class AnalyzerWorker(EventSubscriber):
            stream = StreamName.MEDIA
            events = [EventType.MOVIE_RECEIVED]

            async def handle(self, event_type, payload, raw_event):
                await self.analyze_movie(payload["path"])
    """

    stream: StreamName
    events: list[EventType]
    consumer_name: str = "worker"

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        # Per-service groups so multiple services on one stream each get a copy
        # (shared group would compete and ACK-drop events other services need).
        self.group = f"{settings.redis_consumer_group}:{service_name}"
        self._running = False
        self._dead_letter = EventPublisher(StreamName.DEAD_LETTER)

    @abstractmethod
    async def handle(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        raw_event: dict[str, str],
    ) -> None:
        """Process an incoming event. Implement in each service."""
        ...

    async def start(self) -> None:
        """Start the event consumption loop."""
        redis = await get_redis()

        # Ensure consumer group exists (idempotent)
        try:
            await redis.xgroup_create(
                self.stream.value,
                self.group,
                id="0",
                mkstream=True,
            )
            logger.info("Consumer group created", group=self.group, stream=self.stream.value)
        except Exception:
            pass  # group already exists

        self._running = True
        logger.info(
            "Event subscriber started",
            service=self.service_name,
            stream=self.stream.value,
            events=[e.value for e in self.events],
        )

        while self._running:
            try:
                await self._poll(redis)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Subscriber poll error", error=str(exc))
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Gracefully stop the subscriber."""
        self._running = False
        logger.info("Event subscriber stopping", service=self.service_name)

    async def _poll(self, redis: aioredis.Redis) -> None:
        """Read and process new messages from the stream."""
        messages = await redis.xreadgroup(
            groupname=self.group,
            consumername=f"{self.service_name}-{self.consumer_name}",
            streams={self.stream.value: ">"},
            count=10,
            block=5000,  # block up to 5s waiting for messages
        )

        if not messages:
            return

        for _stream, entries in messages:
            for entry_id, fields in entries:
                await self._process(redis, entry_id, fields)

    async def _process(
        self,
        redis: aioredis.Redis,
        entry_id: str,
        fields: dict[str, str],
    ) -> None:
        """Process a single event with retry logic."""
        event_type_str = fields.get("event_type", "")

        # Filter: only process events this worker cares about
        subscribed = [e.value for e in self.events]
        if subscribed and event_type_str not in subscribed:
            await redis.xack(self.stream.value, self.group, entry_id)
            return

        try:
            event_type = EventType(event_type_str)
            payload = json.loads(fields.get("payload", "{}"))
        except (ValueError, json.JSONDecodeError) as exc:
            logger.error("Malformed event", entry_id=entry_id, error=str(exc))
            await redis.xack(self.stream.value, self.group, entry_id)
            return

        retry_count = 0
        while retry_count <= MAX_RETRIES:
            try:
                await self.handle(event_type, payload, fields)
                await redis.xack(self.stream.value, self.group, entry_id)
                logger.info(
                    "Event processed",
                    event_type=event_type.value,
                    entry_id=entry_id,
                    service=self.service_name,
                )
                return
            except Exception as exc:
                retry_count += 1
                if retry_count > MAX_RETRIES:
                    logger.error(
                        "Event permanently failed — sending to dead-letter queue",
                        event_type=event_type.value,
                        entry_id=entry_id,
                        error=str(exc),
                    )
                    await self._dead_letter.publish_to_dead_letter(
                        original_event=fields,
                        error=str(exc),
                        retry_count=retry_count,
                    )
                    await redis.xack(self.stream.value, self.group, entry_id)
                    return
                backoff = RETRY_BACKOFF_SECONDS[min(retry_count - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                logger.warning(
                    "Event handling failed, retrying",
                    event_type=event_type.value,
                    retry=retry_count,
                    backoff=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(backoff)
