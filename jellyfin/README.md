# Jellyfin (Netflix-like web theme)

Standalone Jellyfin Compose for this homeserver. Library is the same tree the
media-platform organizer writes:

`/opt/media-platform/data/library` → container `/media`

## Start

```bash
cd /opt/media-platform/app/jellyfin   # or your checkout path
docker compose up -d
```

Requires external Docker network `media_network` (create once if missing):

```bash
docker network create media_network
```

If platform services use `mp_media` instead, either join Jellyfin to that
network or set `JELLYFIN_URL` to a host-reachable URL (e.g. `http://127.0.0.1:8096`).

## Netflix-like home theme

Theme file: [`custom.css`](./custom.css) (JellyFlix base + local home tweaks).

### Option A — Dashboard (manual)

1. Open Jellyfin → **Dashboard → General**
2. Scroll to **Custom CSS**
3. Paste the contents of `custom.css`
4. Save → hard-refresh the browser (Ctrl+F5)

### Option B — API script (recommended)

Create an API key in Jellyfin (**Dashboard → API Keys**), then:

```bash
export JELLYFIN_URL=http://127.0.0.1:8096
export JELLYFIN_API_KEY=your_key
chmod +x apply-theme.sh
./apply-theme.sh
```

The same key can also go in the media-platform `.env` as `JELLYFIN_API_KEY`
(used for library refresh after organize).

### After updates

If you change `custom.css` in git, re-run `./apply-theme.sh` (or re-paste).
Compose mounts the file at `/config/custom-css/netflix.css` inside the
container for reference; Jellyfin still applies CSS from Branding config.

## Accent color

Edit `:root { --accent: #e50914; }` in `custom.css` (Netflix red by default).
