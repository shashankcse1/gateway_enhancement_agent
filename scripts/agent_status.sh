#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/Library/Python/3.9/bin:${PATH:-}"
LABEL="com.gateway.enhancement-agent"
UID_NUM="$(id -u)"

echo "=== Login agent (launchd) ==="
if launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | head -12; then
  :
else
  echo "Not installed. Run: make login-install"
fi

echo ""
echo "=== Daemon ==="
if [[ -f "${ROOT}/.runtime/daemon.pid" ]] && kill -0 "$(cat "${ROOT}/.runtime/daemon.pid")" 2>/dev/null; then
  echo "Running PID $(cat "${ROOT}/.runtime/daemon.pid")"
else
  echo "Not running"
fi

echo ""
echo "=== Agent state ==="
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
export AGENT_SOURCE_ROOT="$ROOT"
export AGENT_DATA_DIR="${HOME}/Library/Application Support/gateway-enhancement-agent"
export PYTHONPATH="${ROOT}/src"
gateway-agent status 2>/dev/null || python3 -m gateway_enhancement_agent status
