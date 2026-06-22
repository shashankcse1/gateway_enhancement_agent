"""Shared configuration and path resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path


def source_root() -> Path:
    """Code and config location (read-only for launchd-friendly installs)."""
    override = os.environ.get("AGENT_SOURCE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def project_root() -> Path:
    """Writable data root: state, artifacts. Override for launchd (Application Support)."""
    override = os.environ.get("AGENT_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return source_root()


def config_dir() -> Path:
    return source_root() / "config"


def load_json(name: str) -> dict:
    path = config_dir() / name
    return json.loads(path.read_text(encoding="utf-8"))


def target_repo() -> Path:
    env = os.environ.get("TARGET_REPO", "").strip().strip('"').strip("'")
    if env:
        return Path(env).expanduser().resolve()
    default = source_root() / "target-repo"
    if default.exists():
        return default.resolve()
    raise FileNotFoundError(
        "TARGET_REPO is not set. Export TARGET_REPO to your gateway platform checkout "
        "(see .env.example)."
    )


def runtime_dir() -> Path:
    path = project_root() / ".runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifacts_dir() -> Path:
    path = project_root() / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path
