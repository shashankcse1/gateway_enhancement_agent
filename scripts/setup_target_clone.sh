#!/usr/bin/env bash
# Clone TARGET_REPO into Application Support for launchd-safe read/write (Desktop TCC bypass).
set -euo pipefail

SOURCE="${1:-}"
DEST="${2:-${HOME}/Library/Application Support/gateway-enhancement-agent/target-clone}"

if [[ -z "$SOURCE" ]]; then
  echo "Usage: setup_target_clone.sh <source_repo> [dest_clone]"
  exit 1
fi

if [[ ! -d "${SOURCE}/.git" ]]; then
  echo "Source is not a git repository: ${SOURCE}"
  exit 1
fi

mkdir -p "$(dirname "${DEST}")"
BRANCH="$(git -C "${SOURCE}" rev-parse --abbrev-ref HEAD)"
COMMIT="$(git -C "${SOURCE}" rev-parse HEAD)"

if [[ ! -d "${DEST}/.git" ]]; then
  echo "Cloning ${SOURCE} (${BRANCH}) -> ${DEST}"
  git clone --branch "${BRANCH}" "file://${SOURCE}" "${DEST}"
else
  echo "Refreshing clone ${DEST} (${BRANCH} @ ${COMMIT:0:8})"
  git -C "${DEST}" fetch "file://${SOURCE}" "${BRANCH}:${BRANCH}" 2>/dev/null || git -C "${DEST}" fetch "file://${SOURCE}"
  git -C "${DEST}" checkout "${BRANCH}"
  git -C "${DEST}" reset --hard "${COMMIT}"
fi

# Propagate remotes from source (origin).
while IFS= read -r remote; do
  url="$(git -C "${SOURCE}" remote get-url "${remote}" 2>/dev/null || true)"
  if [[ -z "$url" ]]; then
    continue
  fi
  if git -C "${DEST}" remote get-url "${remote}" >/dev/null 2>&1; then
    git -C "${DEST}" remote set-url "${remote}" "${url}"
  else
    git -C "${DEST}" remote add "${remote}" "${url}"
  fi
done < <(git -C "${SOURCE}" remote)

echo "Agent clone ready: ${DEST} on ${BRANCH} (${COMMIT:0:8})"
