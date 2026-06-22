#!/usr/bin/env bash
# Single SDLC cycle for launchd/cron — logs to .runtime/scheduler.log
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

LOG=".runtime/scheduler.log"
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

{
  echo "=== scheduled run $TS ==="
  python3 -m gateway_enhancement_agent run
  echo "=== finished $TS exit=$? ==="
} >>"$LOG" 2>&1
