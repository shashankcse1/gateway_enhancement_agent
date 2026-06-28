#!/usr/bin/env bash
# One-shot repair: sync configs, refresh pylibs/clone, fix launchd env, restart agents.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

SUPPORT="${HOME}/Library/Application Support/gateway-enhancement-agent"
SOURCE="${TARGET_REPO:-}"
CLONE="${SUPPORT}/target-clone"

echo "=== 1. Sync Application Support config (GitHub-only push) ==="
mkdir -p "${SUPPORT}/config"
cp -Rf "${ROOT}/config/." "${SUPPORT}/config/"

echo "=== 2. Write launchd-safe .env (no Desktop TARGET_REPO override) ==="
ENV_DEST="${SUPPORT}/.env"
if [[ -f .env ]]; then
  grep -v '^TARGET_REPO=' .env | grep -v '^BITBUCKET_' >"${ENV_DEST}" || true
  {
    echo "GIT_PUSH_REMOTES=origin"
    echo "AGENT_USE_APP_SUPPORT_CLONE=1"
    [[ -n "${SOURCE}" ]] && echo "TARGET_REPO_SOURCE=${SOURCE}"
  } >>"${ENV_DEST}"
  chmod 600 "${ENV_DEST}"
fi

echo "=== 3. Refresh gateway clone + mirror ==="
if [[ -n "${SOURCE}" && -d "${SOURCE}/.git" ]]; then
  bash "${ROOT}/scripts/setup_target_clone.sh" "${SOURCE}" "${CLONE}"
  git -C "${CLONE}" remote remove bitbucket 2>/dev/null || true
  git -C "${CLONE}" config user.name "${GIT_USER_NAME:-Gateway Enhancement Agent}" 2>/dev/null || \
    git -C "${CLONE}" config user.name "Gateway Enhancement Agent"
  git -C "${CLONE}" config user.email "${GIT_USER_EMAIL:-shashankcse@gmail.com}" 2>/dev/null || true
  MIRROR="${SUPPORT}/target-mirror"
  mkdir -p "${MIRROR}/backend/docs/governance" "${MIRROR}/backend/app/routers"
  cp -f "${SOURCE}/backend/docs/governance/"*.md "${MIRROR}/backend/docs/governance/" 2>/dev/null || true
  cp -f "${SOURCE}/backend/AGENTS.md" "${MIRROR}/backend/" 2>/dev/null || true
  cp -f "${SOURCE}/backend/app/routers/gateway.py" "${MIRROR}/backend/app/routers/" 2>/dev/null || true
fi

echo "=== 4. Refresh agent Python libs ==="
python3 -m pip install --target "${SUPPORT}/pylibs" "${ROOT}" -q --upgrade

echo "=== 5. Reinstall LaunchAgents ==="
make login-install

echo "=== 6. Services ==="
brew services start ollama 2>/dev/null || true
if command -v postfix >/dev/null 2>&1; then
  sudo postfix start 2>/dev/null || echo "Run manually: sudo postfix start"
fi

echo ""
echo "=== Permission verification ==="
python3 - <<'PY'
from pathlib import Path
import subprocess
checks = []
clone = Path.home() / "Library/Application Support/gateway-enhancement-agent/target-clone/backend/AGENTS.md"
mirror = Path.home() / "Library/Application Support/gateway-enhancement-agent/target-mirror/backend/AGENTS.md"
for label, p in [("clone read", clone), ("mirror read", mirror)]:
    try:
        ok = p.is_file() and len(p.read_text()) > 100
        checks.append((label, ok))
    except OSError:
        checks.append((label, False))
test = clone.parent.parent / ".runtime/_perm"
try:
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text("ok")
    test.unlink()
    checks.append(("clone write", True))
except OSError:
    checks.append(("clone write", False))
try:
    r = subprocess.run(["curl", "-sf", "http://127.0.0.1:11434/api/tags"], capture_output=True, timeout=5)
    checks.append(("ollama", r.returncode == 0))
except Exception:
    checks.append(("ollama", False))
try:
    import socket
    s = socket.socket()
    s.settimeout(2)
    checks.append(("postfix :25", s.connect_ex(("127.0.0.1", 25)) == 0))
    s.close()
except Exception:
    checks.append(("postfix :25", False))
for name, ok in checks:
    print(f"  {'OK' if ok else 'FAIL'}: {name}")
PY

echo ""
echo "Done. Foreground check: make agent-status"
