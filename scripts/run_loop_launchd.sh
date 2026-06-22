#!/usr/bin/env bash
# Launchd entrypoint — sets paths then runs the SDLC loop forever.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/Library/Python/3.9/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="${ROOT}/src:${PYTHONPATH:-}"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

INTERVAL="${LOOP_INTERVAL_SECONDS:-3600}"
exec python3 -m gateway_enhancement_agent loop --interval "$INTERVAL"
