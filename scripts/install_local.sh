#!/usr/bin/env bash
# Install gateway-enhancement-agent on this Mac (local only, no cloud).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

echo "Installing gateway-enhancement-agent into user site..."
python3 -m pip install --user -e ".[dev]"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — set TARGET_REPO to your gateway checkout"
fi

BIN_DIR="$(python3 -m site --user-base)/bin"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo ""
  echo "Add to your shell profile (~/.zshrc):"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi

echo ""
echo "Verify install:"
echo "  cd \"$ROOT\""
echo "  make test"
echo "  TARGET_REPO=\"/path/to/gateway\" make validate"
echo "  gateway-agent run"
echo "  make schedule-install   # macOS LaunchAgent (hourly by default)"
echo "  make daemon-start       # background loop alternative"
