#!/usr/bin/env bash
# Install macOS LaunchAgent to run gateway SDLC cycles on an interval.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LABEL="com.gateway.enhancement-agent"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
INTERVAL="${LOOP_INTERVAL_SECONDS:-3600}"
TARGET="${TARGET_REPO:-}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  INTERVAL="${LOOP_INTERVAL_SECONDS:-$INTERVAL}"
  TARGET="${TARGET_REPO:-$TARGET}"
fi

if [[ -z "$TARGET" ]]; then
  echo "TARGET_REPO is not set in .env"
  exit 1
fi

USER_BIN="$(python3 -m site --user-base)/bin"
AGENT_BIN="${USER_BIN}/gateway-agent"

if [[ -x "$AGENT_BIN" ]]; then
  PROGRAM="$AGENT_BIN"
  ARG_LINES='    <string>run</string>'
else
  PROGRAM="$(command -v python3)"
  ARG_LINES='    <string>-m</string>
    <string>gateway_enhancement_agent</string>
    <string>run</string>'
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${ROOT}/.runtime"

cat >"$PLIST_DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PROGRAM}</string>
${ARG_LINES}
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartInterval</key>
  <integer>${INTERVAL}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${ROOT}/.runtime/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/.runtime/launchd.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${USER_BIN}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>TARGET_REPO</key>
    <string>${TARGET}</string>
    <key>PYTHONPATH</key>
    <string>${ROOT}/src</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null || true
launchctl enable "gui/$(id -u)/${LABEL}" 2>/dev/null || true

echo "Scheduled gateway enhancement agent installed."
echo "  Label:       ${LABEL}"
echo "  Interval:    ${INTERVAL}s"
echo "  TARGET_REPO: ${TARGET}"
echo "  Program:     ${PROGRAM}"
echo ""
echo "Note: macOS may block LaunchAgents under Desktop without Full Disk Access."
echo "Reliable option while logged in: make daemon-start"
echo "  tail -f ${ROOT}/.runtime/daemon.log"
