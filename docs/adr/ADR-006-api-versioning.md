# ADR-006: API Versioning Strategy

**Status:** Accepted
**Date:** 2026-07-20

## Decision

Use **URL path versioning** for the Media API.

## Format

```
/api/v1/movies
/api/v1/downloads
/api/v2/movies       ← future breaking change
```

## Rules

1. All API routes are prefixed with `/api/v{N}/`
2. The current stable version is `v1`
3. A new version is created only for **breaking changes**
4. Old versions are kept for at least 2 minor releases before deprecation
5. Deprecation is announced via response header: `Deprecation: true`
6. Internal service-to-service calls use events (not HTTP) — versioning only applies to external-facing API

## Router structure in FastAPI

```python
from fastapi import APIRouter

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(movies_router, prefix="/movies")
v1_router.include_router(downloads_router, prefix="/downloads")
```

## Why URL versioning over Header versioning

- Easier to test in browser / curl without custom headers
- Clearly visible in Nginx logs
- Works with Swagger UI without extra configuration
