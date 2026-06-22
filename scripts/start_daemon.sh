#!/usr/bin/env bash
# Background continuous loop (alternative to launchd interval).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p .runtime

export PATH="${HOME}/Library/Python/3.9/bin:${PATH:-}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PID_FILE=".runtime/daemon.pid"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Daemon already running (PID $(cat "$PID_FILE"))"
  exit 0
fi

INTERVAL="${LOOP_INTERVAL_SECONDS:-3600}"
nohup python3 -m gateway_enhancement_agent loop --interval "$INTERVAL" \
  >>.runtime/daemon.log 2>&1 &
echo $! >"$PID_FILE"
echo "Daemon started PID $(cat "$PID_FILE") — log: .runtime/daemon.log"
