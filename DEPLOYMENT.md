# Server Deployment Guideline

What to do on the **server** after checking out / pulling this codebase.

Target layout assumes Ubuntu + Docker Compose, with data under `/opt/media-platform` (see `scripts/bootstrap.sh`).

> **Maintainer rule:** Whenever platform code, Compose, env keys, migrations, or deploy steps change, update **this file in the same change**. Treat `DEPLOYMENT.md` as part of the deliverable, not optional docs.

---

## Current platform surface (as of this treesddd)

| Area | What ships |
|------|------------|
| Movie pipeline | Telegram file ingest → analyze → metadata → subtitles → quality → organize → Jellyfin |
| Torrents | Magnet / `.torrent` / `qbittorrent://` via Telegram → qBittorrent → same pipeline |
| HTTP downloads | `POST /api/v1/downloads` → download-service |
| Quality | Score / upgrade / keep_existing; library replace on upgrade |
| Subtitles | OpenSubtitles + SubDL (real providers); no placeholder SRTs |
| Dedup / storage / health | duplicate-service, storage-service, health-service |
| Live TV / Radio | M3U import, EPG (XMLTV), dashboard players, recordings, Jellyfin M3U/XMLTV export |
| Dashboard | `/dashboard/` — Overview, Live TV, Guide, Radio, Recordings |
| AI (optional) | ai-service + Ollama (`--profile ai`) |

### Compose services (always-on unless noted)

| Container | Service |
|-----------|---------|
| `mp_workflow_engine` | workflow-engine |
| `mp_media_api` | media-api |
| `mp_telegram_bot_api` | Local Telegram Bot API (large files) |
| `mp_telegram_service` | telegram-service |
| `mp_analyzer_service` | analyzer-service |
| `mp_metadata_service` | metadata-service |
| `mp_subtitle_service` | subtitle-service |
| `mp_organizer_service` | organizer-service |
| `mp_quality_service` | quality-service |
| `mp_download_service` | download-service |
| `mp_duplicate_service` | duplicate-service |
| `mp_storage_service` | storage-service |
| `mp_health_service` | health-service |
| `mp_entertainment_service` | entertainment-service |
| `mp_dashboard` | dashboard |
| `mp_ai_service` | ai-service (needs Ollama reachable) |
| `mp_qbittorrent` | **profile `torrents` only** |
| `mp_ollama` | **profile `ai` only** |

Infrastructure (`compose/infrastructure.yml`): Postgres, Redis, Nginx.

---

## 1. Prerequisites

- Ubuntu 22.04+ (or similar)
- Docker Engine + Compose plugin
- Git
- Enough disk for library + torrents + Docker images
- Outbound HTTPS for TMDb, OpenSubtitles, SubDL, EPG, Ollama pulls

First-time host prep (optional helper):

```bash
sudo ./scripts/bootstrap.sh
```

That creates `/opt/media-platform` directories and Docker networks (`mp_frontend`, `mp_backend`, `mp_media`).

---

## 2. Get the code on the server

```bash
# Example: deploy from this repo into /opt/media-platform/app
sudo mkdir -p /opt/media-platform/app
cd /opt/media-platform/app

# First time
git clone <YOUR_REPO_URL> .

# Later updates
git fetch origin
git pull origin <branch>
```

Work from the project root (folder that contains `compose/`, `services/`, `.env.sample`, `DEPLOYMENT.md`).

---

## 3. Environment file

```bash
# First deploy
cp .env.sample .env
nano .env   # or vim

# On updates: merge new keys from .env.sample into your existing .env
# Do NOT overwrite a production .env blindly.
diff -u .env .env.sample | less
```

Whenever `.env.sample` gains keys in a pull, those keys must be added to the server `.env` before rebuild.

### Required / high-priority keys

| Area | Variables |
|------|-----------|
| DB / Redis | `POSTGRES_*`, `REDIS_*` (must match Compose) |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` |
| Metadata | `TMDB_API_KEY` |
| Subtitles | `OPENSUBTITLES_API_KEY` (+ optional `OPENSUBTITLES_USERNAME` / `OPENSUBTITLES_PASSWORD`), `SUBDL_API_KEY`, `SUBTITLE_LANGUAGES` |
| Jellyfin | `JELLYFIN_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_USER_ID` |
| Public URL | `PUBLIC_BASE_URL` (host used in Live TV M3U links, e.g. `http://192.168.1.10` or your domain) |

### Optional feature keys

| Feature | Variables / notes |
|---------|-------------------|
| Quality prefs | `QUALITY_PREFERENCE`, `QUALITY_PREFER_HDR`, `QUALITY_PREFER_HEVC` |
| qBittorrent | `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`, `QBITTORRENT_SAVE_PATH=/downloads/torrents`, `QBITTORRENT_CATEGORY`, `QBITTORRENT_POLL_INTERVAL_SECONDS`, `QBITTORRENT_TIMEOUT_SECONDS` |
| Live TV EPG | `EPG_URL` (XMLTV or `.xml.gz`), `EPG_REFRESH_HOURS` |
| Recordings | `RECORDING_MAX_DURATION_SECONDS` (default 14400), `RECORDING_ORGANIZE_TO_LIBRARY` |
| Storage / health | `STORAGE_*_THRESHOLD_GB`, `STORAGE_*_RETENTION_DAYS`, `HEALTH_SCAN_INTERVAL_SECONDS` |
| AI | `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS` (use Compose `--profile ai`) |

Change default passwords from sample values before exposing ports. Placeholder subtitle API keys are ignored by the subtitle service.

---

## 4. Docker networks (if bootstrap was skipped)

```bash
docker network create mp_frontend 2>/dev/null || true
docker network create mp_backend 2>/dev/null || true
docker network create mp_media 2>/dev/null || true
```

Ensure data dirs exist and are writable:

```bash
sudo mkdir -p /opt/media-platform/{data/{library,downloads,downloads/torrents,subtitles,metadata,cache,temp,recordings,qbittorrent/config,ollama,telegram-bot-api},logs}
sudo chown -R "$USER":"$USER" /opt/media-platform/data /opt/media-platform/logs
```

`download-service` and qBittorrent both use `/downloads` inside containers, mounted from `/opt/media-platform/data/downloads` on the host.

---

## 5. Database migrations

Run **after** Postgres is up (or against a reachable Postgres).

### Option A — from the host (Postgres port published)

```bash
cd /opt/media-platform/app   # project root
python3 -m venv .venv && . .venv/bin/activate
pip install -r shared/requirements.txt
# Ensure .env has POSTGRES_HOST=127.0.0.1 (or localhost) when running on host
alembic upgrade head
```

### Option B — one-off container on the Compose network

```bash
docker compose --env-file .env -f compose/infrastructure.yml up -d postgres
docker run --rm --network mp_backend \
  --env-file .env \
  -e POSTGRES_HOST=postgres \
  -v "$PWD":/app -w /app \
  python:3.12-slim \
  bash -c "pip install -q -r shared/requirements.txt && alembic upgrade head"
```

### Current revisions

| Revision | Purpose |
|----------|---------|
| `0001_initial_schema` | Base tables from SQLAlchemy models |
| `0002_epg_programs` | Live TV `epg_programs` table |

Re-run `alembic upgrade head` on every deploy that includes new files under `alembic/versions/`. When you add a migration in code, document it in this table.

---

## 6. Start / update the stack

Always from the project root:

```bash
# Infrastructure (Postgres, Redis, Nginx)
docker compose --env-file .env -f compose/infrastructure.yml up -d

# Application services (rebuild after code pull)
docker compose --env-file .env \
  -f compose/infrastructure.yml \
  -f compose/services.yml \
  up -d --build
```

### Optional profiles

```bash
# Bundled qBittorrent (WebUI typically on host port 8085)
docker compose --env-file .env \
  -f compose/infrastructure.yml \
  -f compose/services.yml \
  --profile torrents up -d --build

# Ollama + ai-service
docker compose --env-file .env \
  -f compose/infrastructure.yml \
  -f compose/services.yml \
  --profile ai up -d --build

# Pull a model once Ollama is running
docker exec -it mp_ollama ollama pull llama3.2
```

### After every code update (checklist)

1. `git pull`
2. Merge new `.env.sample` keys into `.env`
3. `alembic upgrade head` (or container method above)
4. `docker compose ... up -d --build`
5. `docker compose ... ps` and check logs for unhealthy services
6. Confirm `DEPLOYMENT.md` / `.env.sample` match what you just deployed

Rebuild only what changed (faster example):

```bash
docker compose --env-file .env \
  -f compose/infrastructure.yml -f compose/services.yml \
  up -d --build telegram-service download-service entertainment-service media-api dashboard
```

---

## 7. Post-deploy configuration (product features)

### Telegram ingest

1. Create bot via BotFather; set `TELEGRAM_BOT_TOKEN`
2. For groups: disable privacy (`/setprivacy`) or make bot admin
3. Send `/id` in the group; set `TELEGRAM_ALLOWED_CHAT_IDS`
4. For large files: local Bot API is started as `telegram-bot-api` — set `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`
5. Test file: upload a small `.mkv` / `.mp4` to the group
6. Test torrent: paste a magnet / `.torrent` URL / attach a `.torrent` file (needs qBittorrent configured)

### Torrents (magnet / .torrent)

1. Point `QBITTORRENT_*` at existing WebUI **or** start `--profile torrents`
2. WebUI password must match `QBITTORRENT_PASSWORD`
3. Save path must be shared with `download-service` (`QBITTORRENT_SAVE_PATH=/downloads/torrents` with Compose mounts)
4. When the torrent finishes, download-service stages the largest video into `downloads/incoming` and starts the movie pipeline

### Subtitles

1. Register OpenSubtitles consumer key and/or SubDL API key
2. Set `SUBTITLE_LANGUAGES` (e.g. `en,ml`)
3. Pipeline continues with `SUBTITLE_NOT_FOUND` if nothing is available

### Live TV / Radio

1. Open dashboard: `http://<server>/dashboard/` → **Live TV**
2. Import M3U URL
3. Set `EPG_URL` and use **Refresh EPG** (or wait for scheduled refresh)
4. Add radio stations under **Radio**
5. Schedule recordings under **Recordings** (ffmpeg; max duration from env)
6. Jellyfin Live TV (optional):
   - M3U: `http://<PUBLIC_BASE_URL>/api/v1/entertainment/export/jellyfin.m3u`
   - XMLTV: `http://<PUBLIC_BASE_URL>/api/v1/entertainment/export/jellyfin.xmltv`
7. Ensure `PUBLIC_BASE_URL` is reachable from Jellyfin / browsers

### Jellyfin library

1. Point Jellyfin movie libraries at `/opt/media-platform/data/library/movies`
2. Optional recordings library: `/opt/media-platform/data/library/recordings`
3. API key + user id in `.env` for automatic refresh after organize

---

## 8. Verify deployment

```bash
# Containers
docker compose --env-file .env -f compose/infrastructure.yml -f compose/services.yml ps

# HTTP
curl -s http://127.0.0.1/health
curl -s http://127.0.0.1/api/v1/health
curl -s http://127.0.0.1/api/v1/storage
curl -s http://127.0.0.1/dashboard/ | head
curl -s http://127.0.0.1/api/v1/entertainment/iptv/channels | head

# API docs
# http://<server>/docs
```

Useful logs:

```bash
docker logs -f mp_telegram_service
docker logs -f mp_workflow_engine
docker logs -f mp_download_service
docker logs -f mp_quality_service
docker logs -f mp_entertainment_service
docker logs -f mp_media_api
docker logs -f mp_dashboard
```

---

## 9. Ports (default)

| Port | Service |
|------|---------|
| 80 | Nginx (API + dashboard + stream proxies) |
| 8000 | media-api (also via Nginx `/api/`) |
| 8085 | qBittorrent WebUI (`--profile torrents`) |
| 11434 | Ollama (`--profile ai`) |
| 5432 / 6379 | Postgres / Redis (prefer not exposing publicly) |

Internal service health ports (container-local): workflow `8001`, telegram `8002`, analyzer `8003`, metadata `8004`, subtitle `8005`, organizer `8006`, quality `8007`, download `8008`, duplicate `8009`, storage `8010`, health `8011`, entertainment `8012`, ai `8013`, dashboard `8014`.

Lock down firewall; only publish what you need.

---

## 10. Rollback notes

- Keep the previous Git commit / tag known before `git pull`
- `.env` and `/opt/media-platform/data` are **not** in Git — back them up separately
- To roll back code: `git checkout <previous-sha>` then `up -d --build` and run matching migrations only if you have reverse migrations (prefer restore DB snapshot if schema moved forward)

---

## 11. Quick “update after pull” script (copy/paste)

```bash
#!/bin/sh
set -e
cd /opt/media-platform/app   # adjust to your checkout path

git pull
echo "Review and merge new keys from .env.sample into .env if needed."
echo "If DEPLOYMENT.md or alembic/versions changed, follow those steps."

docker compose --env-file .env -f compose/infrastructure.yml up -d

# Run migrations (adjust method to your setup)
# alembic upgrade head

docker compose --env-file .env \
  -f compose/infrastructure.yml \
  -f compose/services.yml \
  up -d --build

docker compose --env-file .env \
  -f compose/infrastructure.yml \
  -f compose/services.yml \
  ps
```

Add `--profile torrents` and/or `--profile ai` if you use those features.

---

## 12. Doc update checklist (for developers)

When you change the platform, update `DEPLOYMENT.md` in the **same PR/commit** if any of these apply:

- [ ] New / removed Compose service or profile
- [ ] New `.env` / `.env.sample` keys
- [ ] New Alembic revision (add to §5 table)
- [ ] New host paths, ports, or volumes
- [ ] New operator steps (Telegram, qBittorrent, EPG, Jellyfin, etc.)
- [ ] Changed verify commands or container names

Also keep `README.md` linked and accurate at a high level.

---

## Related files

- `.env.sample` — full env template
- `compose/infrastructure.yml` — Postgres, Redis, Nginx
- `compose/services.yml` — all microservices + optional profiles
- `scripts/bootstrap.sh` — first-time Ubuntu host layout
- `README.md` — short feature overview
- `alembic/versions/` — DB migrations
- `docs/adr/` — architecture decisions
