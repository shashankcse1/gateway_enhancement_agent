#!/usr/bin/env bash
# Document macOS permissions for the enhancement agent (GitHub push via origin).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "=== Git remotes (GitHub) ==="
git remote -v 2>/dev/null || true

echo ""
echo "=== macOS permissions checklist ==="
echo "1. Full Disk Access (optional if using Application Support clone):"
echo "   System Settings → Privacy & Security → Full Disk Access"
echo "   Add: $(python3 -c 'import sys; print(sys.executable)')"
echo "2. Local Postfix for summary email:"
echo "   sudo postfix start"
echo "3. Ollama for implement agents:"
echo "   brew services start ollama"
echo "4. GitHub push (autonomous agent uses origin only):"
echo "   git push origin main"
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

echo "Done."
