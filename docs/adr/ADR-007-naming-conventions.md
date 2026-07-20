# ADR-007: Naming Conventions

**Status:** Accepted
**Date:** 2026-07-20

## Purpose

Consistent naming prevents confusion as the codebase grows to 14+ services.

---

## Python

| Item | Convention | Example |
|---|---|---|
| Files | `snake_case` | `download_service.py` |
| Classes | `PascalCase` | `DownloadService` |
| Functions | `snake_case` | `get_download_by_id()` |
| Variables | `snake_case` | `movie_path` |
| Constants | `SCREAMING_SNAKE` | `MAX_RETRY_COUNT` |
| Private | `_leading_underscore` | `_parse_filename()` |
| Type aliases | `PascalCase` | `MovieId = str` |

---

## Database

| Item | Convention | Example |
|---|---|---|
| Tables | `snake_case` plural | `movies`, `download_jobs` |
| Columns | `snake_case` | `created_at`, `tmdb_id` |
| Primary key | `id` (UUID) | `id UUID PRIMARY KEY` |
| Foreign keys | `{table}_id` | `movie_id`, `job_id` |
| Indexes | `idx_{table}_{column}` | `idx_movies_tmdb_id` |
| Timestamps | `created_at`, `updated_at`, `deleted_at` | — |
| Boolean | `is_{state}` | `is_deleted`, `is_active` |

---

## Docker / Services

| Item | Convention | Example |
|---|---|---|
| Service names | `{name}-service` | `telegram-service` |
| Container names | `mp_{name}` | `mp_postgres`, `mp_redis` |
| Network names | `mp_{zone}` | `mp_backend`, `mp_frontend` |
| Volume names | `mp_{purpose}` | `mp_postgres_data` |
| Image tags | `{service}:{version}` | `media-api:0.1.0` |

---

## Events

| Item | Convention | Example |
|---|---|---|
| Event types | `domain.action` | `movie.received`, `subtitle.downloaded` |
| Stream names | `stream:{domain}` | `stream:media`, `stream:downloads` |
| Consumer group | `media-platform` | — |

---

## Files & Directories

| Item | Convention | Example |
|---|---|---|
| Service dirs | `{name}-service/` | `telegram-service/` |
| Config files | `{purpose}.yml` | `infrastructure.yml` |
| Scripts | `{action}.sh` | `bootstrap.sh`, `backup.sh` |
| Movie folder | `{Title} ({Year})/` | `Interstellar (2014)/` |
| Movie file | `{Title} ({Year}).{ext}` | `Interstellar (2014).mkv` |
| Subtitle file | `{Title} ({Year}).{lang}.srt` | `Interstellar (2014).en.srt` |
