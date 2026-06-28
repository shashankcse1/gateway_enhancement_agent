#!/usr/bin/env bash
# Install LaunchAgent that survives Mac login/restart (no Desktop script execution).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LABEL="com.gateway.enhancement-agent"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
SUPPORT="${HOME}/Library/Application Support/gateway-enhancement-agent"
SRC_LINK="${HOME}/.gateway-enhancement-agent-src"
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

LOCAL_LLM_ENABLED="${LOCAL_LLM_ENABLED:-1}"
LOCAL_LLM_AUTO_IMPLEMENT="${LOCAL_LLM_AUTO_IMPLEMENT:-1}"
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://127.0.0.1:11434}"
LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-qwen2.5-coder:7b}"
AGENT_FULLY_AUTONOMOUS="${AGENT_FULLY_AUTONOMOUS:-1}"
AGENT_AUTO_PUSH="${AGENT_AUTO_PUSH:-1}"
AGENT_MERGE_BRANCH="${AGENT_MERGE_BRANCH:-}"

if [[ -z "$TARGET" ]]; then
  echo "TARGET_REPO is not set in .env"
  exit 1
fi

python3 -m pip install --user -e ".[dev]" -q 2>/dev/null || true

# Space-free symlink so launchd PYTHONPATH is reliable.
ln -sfn "$ROOT" "$SRC_LINK"

PYTHON_BIN="$(PYTHONPATH="${SRC_LINK}/src" python3 -c "import sys; print(sys.executable)")"

mkdir -p "${SUPPORT}" "${SUPPORT}/.runtime" "${SUPPORT}/artifacts" "${HOME}/Library/LaunchAgents"

echo "Syncing governance mirror for launchd (Desktop-safe read)..."
MIRROR="${SUPPORT}/target-mirror"
mkdir -p "${MIRROR}/backend/docs/governance" "${MIRROR}/backend/app/routers" "${SUPPORT}/config"
cp -Rf "${ROOT}/config/." "${SUPPORT}/config/"
if [[ -d "${TARGET}/backend" ]]; then
  cp -f "${TARGET}/backend/docs/governance/"*.md "${MIRROR}/backend/docs/governance/" 2>/dev/null || true
  cp -f "${TARGET}/backend/AGENTS.md" "${MIRROR}/backend/" 2>/dev/null || true
  cp -f "${TARGET}/backend/app/routers/gateway.py" "${MIRROR}/backend/app/routers/" 2>/dev/null || true
fi
python3 -m pip install --target "${SUPPORT}/pylibs" "${ROOT}" -q --upgrade

ENV_DEST="${SUPPORT}/.env"
if [[ -f .env ]]; then
  cp -f .env "${ENV_DEST}"
  chmod 600 "${ENV_DEST}"
fi

cat >"${SUPPORT}/run_loop.sh" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail
export AGENT_SOURCE_ROOT="${SRC_LINK}"
export AGENT_DATA_DIR="${SUPPORT}"
export PYTHONPATH="${SUPPORT}/pylibs:${SRC_LINK}/src"
export TARGET_REPO="${TARGET}"
export TARGET_REPO_MIRROR="${SUPPORT}/target-mirror"
export LOOP_INTERVAL_SECONDS="${INTERVAL}"
export AGENT_CONFIG_DIR="${SUPPORT}/config"
export AGENT_BACKGROUND_MODE="1"
export LOCAL_LLM_ENABLED="${LOCAL_LLM_ENABLED}"
export LOCAL_LLM_AUTO_IMPLEMENT="${LOCAL_LLM_AUTO_IMPLEMENT}"
export LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL}"
export LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL}"
export AGENT_FULLY_AUTONOMOUS="${AGENT_FULLY_AUTONOMOUS:-1}"
export AGENT_AUTO_PUSH="${AGENT_AUTO_PUSH:-1}"
export AGENT_MERGE_BRANCH="${AGENT_MERGE_BRANCH:-}"
export WEEKLY_EMAIL_TO="${WEEKLY_EMAIL_TO:-shashankcse@gmail.com}"
export WEEKLY_EMAIL_ENABLED="${WEEKLY_EMAIL_ENABLED:-1}"
if [[ -f "${SUPPORT}/.env" ]]; then set -a; source "${SUPPORT}/.env"; set +a; fi
cd /tmp
exec "${PYTHON_BIN}" -m gateway_enhancement_agent loop --interval "\${LOOP_INTERVAL_SECONDS}"
SCRIPT
chmod +x "${SUPPORT}/run_loop.sh"

bash "${ROOT}/scripts/install_weekly_email.sh"

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
    <string>${SUPPORT}/run_loop.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SUPPORT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${SUPPORT}/.runtime/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${SUPPORT}/.runtime/launchd.err.log</string>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DEST"
launchctl enable "gui/${UID_NUM}/${LABEL}"
sleep 2
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true

echo ""
echo "Login agent installed — starts on every Mac login and auto-restarts."
echo "  Data dir:    ${SUPPORT}"
echo "  Source link: ${SRC_LINK} -> ${ROOT}"
echo "  Python:      ${PYTHON_BIN}"
echo "  TARGET_REPO: ${TARGET}"
echo "  Interval:    ${INTERVAL}s"
echo ""
echo "  make agent-status"
