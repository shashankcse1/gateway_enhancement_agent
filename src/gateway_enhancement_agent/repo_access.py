"""Resolve readable paths for launchd-safe background operation."""

from __future__ import annotations

import os
from pathlib import Path

from gateway_enhancement_agent.config import target_repo


def _mirror_dir() -> Path | None:
    mirror = os.environ.get("TARGET_REPO_MIRROR", "").strip().strip('"').strip("'")
    return Path(mirror).expanduser().resolve() if mirror else None


def _source_repo() -> Path | None:
    source = os.environ.get("TARGET_REPO_SOURCE", "").strip().strip('"').strip("'")
    return Path(source).expanduser().resolve() if source else None


def read_repo_file(rel: str) -> str | None:
    """Read a repo-relative file from mirror, agent clone, or source checkout."""
    rel = rel.lstrip("/")
    candidates: list[Path] = []
    mirror = _mirror_dir()
    if mirror is not None:
        candidates.append(mirror / rel)
    candidates.append(target_repo() / rel)
    source = _source_repo()
    if source is not None:
        candidates.append(source / rel)
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            continue
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None
