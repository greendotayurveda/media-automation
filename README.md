# media-automation

Self-hosted Media Automation Platform (Telegram → analyze → metadata → subtitles → quality → organize → Jellyfin).

**Server deploy / update after checkout:** see [DEPLOYMENT.md](./DEPLOYMENT.md).

## Quick start

```bash
cp .env.sample .env   # fill API keys
docker compose --env-file .env -f compose/infrastructure.yml up -d
docker compose --env-file .env -f compose/infrastructure.yml -f compose/services.yml up -d --build
# Optional AI stack:
docker compose --env-file .env -f compose/infrastructure.yml -f compose/services.yml --profile ai up -d
alembic upgrade head
```

Dashboard: `http://localhost/dashboard/` · API docs: `http://localhost/docs`

### Torrents (qBittorrent)

```bash
# Optional bundled qBittorrent WebUI on :8085
docker compose --env-file .env -f compose/infrastructure.yml -f compose/services.yml --profile torrents up -d

# Set in .env:
# QBITTORRENT_URL=http://qbittorrent:8080
# QBITTORRENT_PASSWORD=...
```

Then paste a magnet / `.torrent` URL / `qbittorrent://` link (or attach a `.torrent` file) in the Telegram group.

## Services

| Phase | Service | Role |
|-------|---------|------|
| 4–6 | workflow, media-api, telegram | Orchestration & ingest |
| 7 | download-service | HTTP/local downloads |
| 8–12 | analyzer → metadata → subtitle → quality → organizer | Movie pipeline |
| 13 | duplicate-service | Dedup after organize |
| 14 | storage-service | Disk reports & cleanup |
| 15 | health-service | Library integrity scans |
| 16 | entertainment-service | IPTV / radio / recordings |
| 17 | dashboard | Web overview UI |
| 18 | ai-service (+ ollama profile) | Recommendations & NL Q&A |
