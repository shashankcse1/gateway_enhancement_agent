#!/usr/bin/env bash
# Install LaunchAgent that emails when the SDLC agent is unhealthy (default every 30 minutes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LABEL="com.gateway.enhancement-agent-health"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
SUPPORT="${HOME}/Library/Application Support/gateway-enhancement-agent"
SRC_LINK="${HOME}/.gateway-enhancement-agent-src"
CHECK_INTERVAL_MINUTES="${HEALTH_ALERT_CHECK_MINUTES:-30}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  CHECK_INTERVAL_MINUTES="${HEALTH_ALERT_CHECK_MINUTES:-$CHECK_INTERVAL_MINUTES}"
fi

INTERVAL_SECONDS=$((CHECK_INTERVAL_MINUTES * 60))

PYTHON_BIN="$(PYTHONPATH="${SRC_LINK}/src" python3 -c "import sys; print(sys.executable)" 2>/dev/null || echo python3)"

mkdir -p "${SUPPORT}/.runtime" "${SUPPORT}/config"
cp -Rf "${ROOT}/config/." "${SUPPORT}/config/" 2>/dev/null || true
python3 -m pip install --target "${SUPPORT}/pylibs" "${ROOT}" -q --upgrade 2>/dev/null || true

cat >"${SUPPORT}/run_health_alert.sh" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail
AGENT_TARGET="${SUPPORT}/target-clone"
export AGENT_SOURCE_ROOT="${SRC_LINK}"
export AGENT_DATA_DIR="${SUPPORT}"
export PYTHONPATH="${SUPPORT}/pylibs:${SRC_LINK}/src"
export AGENT_CONFIG_DIR="${SUPPORT}/config"
if [[ -f "${SUPPORT}/.env" ]]; then set -a; source "${SUPPORT}/.env"; set +a; fi
export TARGET_REPO="\${TARGET_REPO:-\${AGENT_TARGET}}"
export TARGET_REPO_MIRROR="${SUPPORT}/target-mirror"
export AGENT_CONFIG_DIR="${SUPPORT}/config"
cd /tmp
exec "${PYTHON_BIN}" -m gateway_enhancement_agent send-health-alert
SCRIPT
chmod +x "${SUPPORT}/run_health_alert.sh"

cat >"$PLIST_DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SUPPORT}/run_health_alert.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SUPPORT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>${INTERVAL_SECONDS}</integer>
  <key>StandardOutPath</key>
  <string>${SUPPORT}/.runtime/health-alert.out.log</string>
  <key>StandardErrorPath</key>
  <string>${SUPPORT}/.runtime/health-alert.err.log</string>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DEST"
launchctl enable "gui/${UID_NUM}/${LABEL}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true

echo "Health alert agent installed — checks every ${CHECK_INTERVAL_MINUTES} minute(s) (${INTERVAL_SECONDS}s)."
echo "  Recipient: \${HEALTH_ALERT_TO:-same as WEEKLY_EMAIL_TO} (set in .env)"
echo "  Script:    ${SUPPORT}/run_health_alert.sh"
echo ""
echo "  gateway-agent health-check"
echo "  gateway-agent send-health-alert --force"
