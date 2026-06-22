"""Shared configuration and path resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return project_root() / "config"


def load_json(name: str) -> dict:
    path = config_dir() / name
    return json.loads(path.read_text(encoding="utf-8"))


def target_repo() -> Path:
    env = os.environ.get("TARGET_REPO", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    default = project_root() / "target-repo"
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
