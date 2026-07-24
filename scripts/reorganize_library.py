"""
Host entrypoint for smart library reorganize.

Prefer running inside metadata-service (has OMDb/TMDb + DB + library mount):

  docker compose --env-file .env \\
    -f compose/infrastructure.yml -f compose/services.yml \\
    exec metadata-service python -m app.reorganize --verbose

  docker compose --env-file .env \\
    -f compose/infrastructure.yml -f compose/services.yml \\
    exec metadata-service python -m app.reorganize --execute --fetch-metadata --verbose
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Re-export metadata-service CLI when available on PYTHONPATH; otherwise print hint.
try:
    sys.path.insert(0, str(_ROOT / "services" / "metadata-service"))
    from app.reorganize import main  # type: ignore
except Exception as exc:  # noqa: BLE001
    print(
        "Run this inside the metadata-service container instead:\n"
        "  docker compose exec metadata-service python -m app.reorganize --help\n"
        f"Import error: {exc}"
    )
    raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
