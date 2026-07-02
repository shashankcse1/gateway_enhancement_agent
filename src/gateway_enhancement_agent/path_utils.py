"""Repository-relative path normalization."""

from __future__ import annotations

from pathlib import Path

_PATH_REWRITES = (
    ("backend/app/tests/", "backend/tests/"),
)


def normalize_repo_path(rel: str) -> str:
    rel = rel.strip().lstrip("./")
    for old, new in _PATH_REWRITES:
        if rel.startswith(old):
            return new + rel[len(old) :]
    return rel


def allowed_repo_path(rel: str, allowed_prefixes: list[str]) -> bool:
    if ".." in Path(rel).parts:
        return False
    if rel.startswith("backend/app/tests/"):
        return False
    if not allowed_prefixes:
        return True
    return any(rel.startswith(prefix) for prefix in allowed_prefixes)
