#!/usr/bin/env bash
# Shared launchd/runtime environment for status, run, and validate commands.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="${HOME}/Library/Application Support/gateway-enhancement-agent"
SRC_LINK="${HOME}/.gateway-enhancement-agent-src"

export AGENT_SOURCE_ROOT="${AGENT_SOURCE_ROOT:-$SRC_LINK}"
export AGENT_DATA_DIR="${AGENT_DATA_DIR:-$SUPPORT}"
export AGENT_CONFIG_DIR="${AGENT_CONFIG_DIR:-$SUPPORT/config}"
export PYTHONPATH="${AGENT_SOURCE_ROOT}/src:${AGENT_DATA_DIR}/pylibs"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
export AGENT_TOOL_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

if [[ -f "${AGENT_DATA_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${AGENT_DATA_DIR}/.env"
  set +a
fi

SOURCE_TARGET="${TARGET_REPO_SOURCE:-${TARGET_REPO:-}}"
AGENT_TARGET="${AGENT_DATA_DIR}/target-clone"
if [[ "${AGENT_USE_APP_SUPPORT_CLONE:-1}" == "1" ]] && [[ -d "${AGENT_TARGET}/.git" ]]; then
  export TARGET_REPO="${AGENT_TARGET}"
  export TARGET_REPO_SOURCE="${SOURCE_TARGET}"
else
  export TARGET_REPO="${TARGET_REPO:-${SOURCE_TARGET}}"
  export TARGET_REPO_SOURCE="${SOURCE_TARGET}"
fi

export TARGET_REPO_MIRROR="${TARGET_REPO_MIRROR:-${AGENT_DATA_DIR}/target-mirror}"
