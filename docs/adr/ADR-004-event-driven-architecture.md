# ADR-004: Event-Driven Microservices

**Status:** Accepted
**Date:** 2026-07-20

## Context

We need to decide on the overall architectural pattern for how services interact.

## Decision

Use an **event-driven microservices** architecture where services communicate exclusively via Redis Stream events.

## Pipeline Flow

```
Telegram → [MOVIE_RECEIVED] → Workflow Engine
                                    │
                    ┌───────────────┤
                    ▼               ▼
              Analyzer        (parallel future)
            [MEDIA_ANALYZED]
                    │
                    ▼
              Metadata
          [METADATA_IDENTIFIED]
                    │
                    ▼
              Subtitle
          [SUBTITLE_DOWNLOADED]
                    │
                    ▼
              Quality Check
           [QUALITY_CHECKED]
                    │
                    ▼
              Organizer
            [FILE_ORGANIZED]
                    │
                    ▼
              Jellyfin refresh
              Telegram notify
```

## Benefits

- **Loose coupling:** Services don't know about each other — only about events
- **Independent scaling:** Each service can run multiple workers
- **Fault isolation:** One service failing doesn't crash others
- **Replayability:** Events are persisted — can replay failed pipelines
- **Extensibility:** Add new services by subscribing to existing events (no code changes elsewhere)

## Rules

1. Services **never** call each other's HTTP APIs directly
2. All state changes produce an event
3. Every event has a `correlation_id` to trace a full pipeline run
4. Failed events go to the dead-letter queue after 3 retries
