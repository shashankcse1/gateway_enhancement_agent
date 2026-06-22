#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
pip install -e . -q
INTERVAL="${LOOP_INTERVAL_SECONDS:-3600}"
MAX="${MAX_CYCLES:-0}"
python3 -m gateway_enhancement_agent loop --interval "$INTERVAL" --max-cycles "$MAX" "$@"
