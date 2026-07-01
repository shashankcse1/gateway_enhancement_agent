#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/agent_env.sh"

LABEL="com.gateway.enhancement-agent"
UID_NUM="$(id -u)"
PYTHON_BIN="${PYTHON_BIN:-/Applications/Xcode.app/Contents/Developer/usr/bin/python3}"

echo "=== Login agent (launchd) ==="
if launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | head -14; then
  :
else
  echo "Not installed. Run: make login-install"
fi

echo ""
echo "=== Paths ==="
echo "Checkout:     ${ROOT}"
echo "Source link:  ${AGENT_SOURCE_ROOT}"
echo "Data dir:     ${AGENT_DATA_DIR}"
echo "Target repo:  ${TARGET_REPO}"
if [[ -n "${TARGET_REPO_SOURCE:-}" && "${TARGET_REPO_SOURCE}" != "${TARGET_REPO}" ]]; then
  echo "Source repo:  ${TARGET_REPO_SOURCE}"
fi
LOG_FILE="${AGENT_DATA_DIR}/.runtime/agent.log"
if [[ -f "${LOG_FILE}" ]]; then
  echo "Progress log: ${LOG_FILE}"
  echo "  tail -f \"${LOG_FILE}\""
fi

echo ""
echo "=== Agent state ==="
cd /tmp
"${PYTHON_BIN}" -m gateway_enhancement_agent status
