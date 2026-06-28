#!/usr/bin/env bash
# Install LaunchAgent for weekly gateway summary email (Sundays 09:00 local).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LABEL="com.gateway.enhancement-agent-weekly-email"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
SUPPORT="${HOME}/Library/Application Support/gateway-enhancement-agent"
SRC_LINK="${HOME}/.gateway-enhancement-agent-src"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON_BIN="$(PYTHONPATH="${SRC_LINK}/src" python3 -c "import sys; print(sys.executable)" 2>/dev/null || echo python3)"

if [[ -f .env ]]; then
  cp -f .env "${SUPPORT}/.env"
  chmod 600 "${SUPPORT}/.env"
fi

cat >"${SUPPORT}/run_weekly_email.sh" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail
export AGENT_SOURCE_ROOT="${SRC_LINK}"
export AGENT_DATA_DIR="${SUPPORT}"
export PYTHONPATH="${SUPPORT}/pylibs:${SRC_LINK}/src"
export AGENT_CONFIG_DIR="${SUPPORT}/config"
if [[ -f "${SUPPORT}/.env" ]]; then set -a; source "${SUPPORT}/.env"; set +a; fi
cd /tmp
exec "${PYTHON_BIN}" -m gateway_enhancement_agent send-weekly-report --force
SCRIPT
chmod +x "${SUPPORT}/run_weekly_email.sh"

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
    <string>${SUPPORT}/run_weekly_email.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SUPPORT}</string>
  <key>RunAtLoad</key>
  <false/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>0</integer>
    <key>Hour</key>
    <integer>9</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${SUPPORT}/.runtime/weekly-email.out.log</string>
  <key>StandardErrorPath</key>
  <string>${SUPPORT}/.runtime/weekly-email.err.log</string>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DEST"
launchctl enable "gui/${UID_NUM}/${LABEL}"

echo "Weekly email agent installed — Sundays at 09:00 local time."
echo "  Recipient: \${WEEKLY_EMAIL_TO:-shashankcse@gmail.com} (set in .env)"
echo "  Script:    ${SUPPORT}/run_weekly_email.sh"
echo ""
echo "  gateway-agent weekly-report"
echo "  gateway-agent send-weekly-report --force"
