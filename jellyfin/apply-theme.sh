#!/usr/bin/env bash
# Apply jellyfin/custom.css to Jellyfin Branding.CustomCss via API.
#
# Usage (on the homeserver):
#   export JELLYFIN_URL=http://127.0.0.1:8096
#   export JELLYFIN_API_KEY=your_admin_api_key
#   ./apply-theme.sh
#
# Or with args:
#   ./apply-theme.sh http://127.0.0.1:8096 YOUR_API_KEY

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSS_FILE="${SCRIPT_DIR}/custom.css"

JELLYFIN_URL="${1:-${JELLYFIN_URL:-http://127.0.0.1:8096}}"
JELLYFIN_API_KEY="${2:-${JELLYFIN_API_KEY:-}}"

if [[ ! -f "$CSS_FILE" ]]; then
  echo "Missing CSS file: $CSS_FILE" >&2
  exit 1
fi

if [[ -z "$JELLYFIN_API_KEY" ]]; then
  echo "Set JELLYFIN_API_KEY (Dashboard → API Keys) or pass as 2nd arg." >&2
  exit 1
fi

JELLYFIN_URL="${JELLYFIN_URL%/}"
# Allow host:port without scheme
if [[ "$JELLYFIN_URL" != http://* && "$JELLYFIN_URL" != https://* ]]; then
  JELLYFIN_URL="http://${JELLYFIN_URL}"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Current branding (keep disclaimer / splash settings)
curl -fsS \
  -H "X-Emby-Token: ${JELLYFIN_API_KEY}" \
  "${JELLYFIN_URL}/System/Configuration/branding" \
  >"${TMP_DIR}/branding.json" || {
  echo "Failed to read branding config from ${JELLYFIN_URL}" >&2
  exit 1
}

python3 - "$CSS_FILE" "${TMP_DIR}/branding.json" "${TMP_DIR}/payload.json" <<'PY'
import json
import sys
from pathlib import Path

css_path, branding_path, out_path = sys.argv[1:4]
css = Path(css_path).read_text(encoding="utf-8")
try:
    branding = json.loads(Path(branding_path).read_text(encoding="utf-8"))
except json.JSONDecodeError:
    branding = {}

if not isinstance(branding, dict):
    branding = {}

branding["CustomCss"] = css
# Preserve common fields with safe defaults
branding.setdefault("LoginDisclaimer", branding.get("LoginDisclaimer") or "")
branding.setdefault("SplashscreenEnabled", bool(branding.get("SplashscreenEnabled", False)))

Path(out_path).write_text(json.dumps(branding), encoding="utf-8")
PY

curl -fsS -X POST \
  -H "X-Emby-Token: ${JELLYFIN_API_KEY}" \
  -H "Content-Type: application/json" \
  --data-binary @"${TMP_DIR}/payload.json" \
  "${JELLYFIN_URL}/System/Configuration/branding" \
  >/dev/null

echo "Applied Netflix theme CSS to ${JELLYFIN_URL}"
echo "Hard-refresh the Jellyfin web UI (Ctrl+F5) to see it."
