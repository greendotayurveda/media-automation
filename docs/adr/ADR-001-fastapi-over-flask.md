# ADR-001: FastAPI over Flask

**Status:** Accepted
**Date:** 2026-07-20

## Context

We need a Python web framework for the Media API and all microservices that expose HTTP endpoints.

## Decision

Use **FastAPI** instead of Flask or Django REST Framework.

## Reasons

| Requirement | FastAPI | Flask |
|---|---|---|
| Native async/await | ✅ First-class | ❌ Requires extensions |
| Auto Swagger docs | ✅ Built-in | ❌ Manual |
| Type safety (Pydantic) | ✅ Native | ❌ Manual |
| Performance | ✅ ASGI (Starlette) | ❌ WSGI |
| Dependency injection | ✅ Built-in | ❌ None |
| WebSocket support | ✅ Native | ⚠️ Extension |

## Consequences

- All service endpoints use `async def`
- Request/response models are Pydantic `BaseModel` classes
- Swagger UI is automatically available at `/docs`
- All services use `uvicorn` as the ASGI server
