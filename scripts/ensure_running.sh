#!/usr/bin/env bash
# Start agent now if not already running (daemon or launchd).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/Library/Python/3.9/bin:${PATH:-}"

LABEL="com.gateway.enhancement-agent"
UID_NUM="$(id -u)"

if launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | grep -E 'state = (running|spawn scheduled)'; then
  if pgrep -f "gateway_enhancement_agent loop" >/dev/null 2>&1; then
    echo "Login agent running (process active)"
    exit 0
  fi
fi

if [[ -f .runtime/daemon.pid ]] && kill -0 "$(cat .runtime/daemon.pid)" 2>/dev/null; then
  echo "Daemon already running PID $(cat .runtime/daemon.pid)"
  exit 0
fi

if [[ -f "${HOME}/Library/LaunchAgents/${LABEL}.plist" ]]; then
  launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null && echo "Started login agent" && exit 0
fi

echo "No login agent installed — starting daemon..."
exec "${ROOT}/scripts/start_daemon.sh"
