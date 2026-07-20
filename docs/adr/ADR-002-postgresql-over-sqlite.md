# ADR-002: PostgreSQL over SQLite

**Status:** Accepted
**Date:** 2026-07-20

## Context

We need a database to store movies, downloads, jobs, quality reports, and all platform state.

## Decision

Use **PostgreSQL 16** instead of SQLite.

## Reasons

- **Concurrency:** 14 microservices write simultaneously — SQLite locks the entire file on every write
- **Full-text search:** `pg_trgm` and `unaccent` extensions enable fast fuzzy movie title search
- **UUID support:** Native `uuid-ossp` extension
- **JSON columns:** Native `jsonb` for flexible metadata storage
- **Reliability:** WAL logging, ACID transactions, crash recovery
- **Future AI:** pgvector extension available for vector similarity search (Phase 18)
- **Alembic migrations:** Works best with PostgreSQL

## Consequences

- Requires PostgreSQL container in Docker Compose
- All services connect via SQLAlchemy async engine
- Alembic manages all schema migrations
- Never use raw SQL strings — always use ORM or parameterized queries
