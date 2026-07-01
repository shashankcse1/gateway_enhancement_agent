"""Sync pushed changes from App Support clone back to the operator source checkout."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.progress_log import log


def source_repo_path() -> Path | None:
    raw = os.environ.get("TARGET_REPO_SOURCE", "").strip().strip('"').strip("'")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def sync_source_after_push(*, merge_branch: str, commit_sha: str | None = None) -> dict:
    source = source_repo_path()
    clone = target_repo().resolve()
    if source is None or not source.is_dir():
        return {"skipped": "TARGET_REPO_SOURCE not set"}
    if source.resolve() == clone:
        return {"skipped": "source and clone are the same path"}
    if not (source / ".git").is_dir():
        return {"skipped": "TARGET_REPO_SOURCE is not a git repository"}
    try:
        _git(source, "fetch", "origin", merge_branch, check=False)
        proc = _git(source, "pull", "--ff-only", "origin", merge_branch)
        log(f"source sync: pulled {merge_branch} into {source}", phase="merge")
        return {
            "synced": True,
            "source_repo": str(source),
            "merge_branch": merge_branch,
            "commit_sha": commit_sha,
            "stdout": (proc.stdout or "").strip()[-500:],
        }
    except SourceSyncError as exc:
        log(f"source sync failed: {exc}", phase="merge")
        return {"synced": False, "error": str(exc), "source_repo": str(source)}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SourceSyncError(f"git {' '.join(args)}: {detail}")
    return proc


class SourceSyncError(RuntimeError):
    pass
