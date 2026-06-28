#!/usr/bin/env bash
# Configure Bitbucket remotes and document macOS permissions for the enhancement agent.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BB_WORKSPACE="${BITBUCKET_WORKSPACE:-shashankcse1}"
AGENT_REPO="${BITBUCKET_AGENT_REPO:-gateway_enhancement_agent}"
GATEWAY_REPO="${BITBUCKET_GATEWAY_REPO:-gateway}"
TARGET="${TARGET_REPO:-}"

add_remote() {
  local repo_path="$1"
  local name="$2"
  local slug="$3"
  if [[ ! -d "${repo_path}/.git" ]]; then
    echo "Skip ${repo_path} (not a git repo)"
    return
  fi
  local url="https://bitbucket.org/${BB_WORKSPACE}/${slug}.git"
  if git -C "${repo_path}" remote get-url "${name}" >/dev/null 2>&1; then
    git -C "${repo_path}" remote set-url "${name}" "${url}"
  else
    git -C "${repo_path}" remote add "${name}" "${url}"
  fi
  echo "  ${repo_path}: remote ${name} -> ${url}"
}

echo "=== Bitbucket remotes (workspace: ${BB_WORKSPACE}) ==="
add_remote "${ROOT}" bitbucket "${AGENT_REPO}"
if [[ -n "$TARGET" && -d "${TARGET}/.git" ]]; then
  add_remote "${TARGET}" bitbucket "${GATEWAY_REPO}"
fi
CLONE="${HOME}/Library/Application Support/gateway-enhancement-agent/target-clone"
if [[ -d "${CLONE}/.git" ]]; then
  add_remote "${CLONE}" bitbucket "${GATEWAY_REPO}"
fi

echo ""
echo "=== macOS permissions checklist ==="
echo "1. Full Disk Access (optional if using Application Support clone):"
echo "   System Settings → Privacy & Security → Full Disk Access"
echo "   Add: $(python3 -c 'import sys; print(sys.executable)')"
echo "2. Local Postfix for summary email:"
echo "   sudo postfix start"
echo "3. Ollama for implement agents:"
echo "   brew services start ollama"
echo ""

if command -v open >/dev/null 2>&1; then
  open "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles" 2>/dev/null || true
fi

if command -v postfix >/dev/null 2>&1; then
  sudo postfix start 2>/dev/null || echo "Postfix start requires sudo (run: sudo postfix start)"
fi

if command -v brew >/dev/null 2>&1; then
  brew services start ollama 2>/dev/null || true
fi

echo "Done. Push with: git push bitbucket HEAD"
