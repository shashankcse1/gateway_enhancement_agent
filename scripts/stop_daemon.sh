#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${ROOT}/.runtime/daemon.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No daemon pid file"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped daemon PID $PID"
else
  echo "Daemon not running (stale pid $PID)"
fi
rm -f "$PID_FILE"
