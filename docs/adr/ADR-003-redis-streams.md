# ADR-003: Redis Streams for Messaging

**Status:** Accepted
**Date:** 2026-07-20

## Context

Services need to communicate asynchronously. Options considered: Redis Streams, RabbitMQ, Kafka, direct HTTP calls.

## Decision

Use **Redis Streams** as the platform event bus.

## Reasons

- **Already in stack:** Redis is required anyway for caching — no new infrastructure
- **Consumer groups:** Built-in support for competing consumers and message acknowledgement
- **Persistence:** Events are stored on disk (unlike PubSub which is fire-and-forget)
- **Dead-letter queue:** Easily implemented as a separate stream
- **Simplicity:** Much simpler ops than Kafka or RabbitMQ for a self-hosted single-node setup
- **Python support:** `redis-py` async client is mature and well-maintained

## Rejected Alternatives

| Option | Reason Rejected |
|---|---|
| RabbitMQ | Extra infrastructure, complex for single developer |
| Kafka | Overkill for expected event volume, heavy resource usage |
| Direct HTTP | Tight coupling, no retry, no persistence |
| Redis PubSub | No persistence — messages lost if consumer is offline |

## Consequences

- All inter-service communication happens via Redis Streams
- Services never call each other's HTTP APIs directly
- Each domain has its own stream (see `StreamName` enum)
- Consumer group name: `media-platform` (configured via `REDIS_CONSUMER_GROUP`)
- Max stream length: 10,000 events per stream (approximate, for memory management)
