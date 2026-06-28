"""Sync governance mirror for launchd-safe reads."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from gateway_enhancement_agent.config import project_root, target_repo


def mirror_dir() -> Path:
    override = os.environ.get("TARGET_REPO_MIRROR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return project_root() / "target-mirror"


def sync_mirror(target: Path | None = None) -> dict:
    repo = target or target_repo()
    dest = mirror_dir()
    dest_backend = dest / "backend"
    gov = dest_backend / "docs" / "governance"
    routers = dest_backend / "app" / "routers"
    gov.mkdir(parents=True, exist_ok=True)
    routers.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    src_backend = repo / "backend"
    if not src_backend.is_dir():
        src_backend = repo

    for pattern in ("docs/governance/*.md",):
        src_gov = src_backend / "docs" / "governance"
        if src_gov.is_dir():
            for src in src_gov.glob("*.md"):
                shutil.copy2(src, gov / src.name)
                copied.append(str(src.relative_to(repo)))

    agents = src_backend / "AGENTS.md"
    if agents.exists():
        shutil.copy2(agents, dest_backend / "AGENTS.md")
        copied.append("backend/AGENTS.md")

    gateway_py = src_backend / "app" / "routers" / "gateway.py"
    if gateway_py.exists():
        shutil.copy2(gateway_py, routers / "gateway.py")
        copied.append("backend/app/routers/gateway.py")

    return {"mirror_dir": str(dest), "target_repo": str(repo), "files_copied": copied}
