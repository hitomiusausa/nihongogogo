#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

if [[ -f "$ROOT_DIR/config/local.env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/config/local.env"
fi

cd "$ROOT_DIR"
mkdir -p data/reports public logs

"$PYTHON" -m nihongo_funding_watch run --since-days "${SINCE_DAYS:-14}"
"$PYTHON" -m nihongo_funding_watch check-duplicates
"$PYTHON" -m nihongo_funding_watch site --since-days "${SINCE_DAYS:-14}" --site-dir public
"$PYTHON" -m nihongo_funding_watch export-csv public/items.csv

if [[ -n "${NIHONGO_WATCH_PUBLIC_DIR:-}" ]]; then
  mkdir -p "$NIHONGO_WATCH_PUBLIC_DIR"
  rsync -a --delete public/ "$NIHONGO_WATCH_PUBLIC_DIR/"
fi
