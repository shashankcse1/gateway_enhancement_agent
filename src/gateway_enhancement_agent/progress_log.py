"""Timestamped progress logging for foreground runs and launchd tail."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _background_mode() -> bool:
    return os.environ.get("AGENT_BACKGROUND_MODE", "").strip().lower() in {"1", "true", "yes"}


def verbose_stderr() -> bool:
    if os.environ.get("AGENT_QUIET", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("AGENT_VERBOSE", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return not _background_mode()


def log_file_path() -> Path | None:
    if os.environ.get("AGENT_LOG_FILE", "1").strip().lower() in {"0", "false", "no"}:
        return None
    data_dir = os.environ.get("AGENT_DATA_DIR", "").strip()
    if not data_dir:
        return None
    return Path(data_dir) / ".runtime" / "agent.log"


def log(message: str, *, phase: str | None = None) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    prefix = f"[{phase}] " if phase else ""
    line = f"{ts} {prefix}{message}"
    if verbose_stderr():
        print(line, file=sys.stderr, flush=True)
    path = log_file_path()
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def log_phase_start(phase: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    log(f"▶ {phase}{suffix}", phase=phase)


def log_phase_done(phase: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    log(f"✓ {phase} done{suffix}", phase=phase)


def log_hint(message: str) -> None:
    log(message, phase="hint")


def log_cycle_banner(cycle_id: int) -> None:
    log(f"{'─' * 50}", phase="cycle")
    log(f"cycle #{cycle_id} started", phase="cycle")
    path = log_file_path()
    if path is not None:
        log_hint(f"tail -f {path}")
