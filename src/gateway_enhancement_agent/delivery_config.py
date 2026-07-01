"""Focused delivery settings for reliable autonomous code commits."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gateway_enhancement_agent.config import load_json


@dataclass
class DeliveryConfig:
    serial_llm: bool
    max_parallel_workers: int
    refresh_competitor_research_hours: int
    forbidden_overwrite_paths: list[str]
    prefer_implement_workers: list[str]
    min_lines_large_files: dict[str, int]

    @classmethod
    def from_env(cls) -> DeliveryConfig:
        try:
            raw = load_json("delivery.json")
        except FileNotFoundError:
            raw = {}
        serial = bool(raw.get("serial_llm", True))
        env_serial = os.environ.get("OLLAMA_SERIAL", "").strip().lower()
        if env_serial in {"0", "false", "no"}:
            serial = False
        elif env_serial in {"1", "true", "yes"}:
            serial = True
        max_workers = int(os.environ.get("PARALLEL_MAX_WORKERS", raw.get("max_parallel_workers", 1)))
        return cls(
            serial_llm=serial,
            max_parallel_workers=max_workers,
            refresh_competitor_research_hours=int(
                os.environ.get("COMPETITOR_RESEARCH_REFRESH_HOURS", raw.get("refresh_competitor_research_hours", 24))
            ),
            forbidden_overwrite_paths=list(raw.get("forbidden_overwrite_paths", [])),
            prefer_implement_workers=list(raw.get("prefer_implement_workers", [])),
            min_lines_large_files=dict(raw.get("min_lines_large_files", {})),
        )

    def is_forbidden_overwrite(self, rel: str) -> bool:
        return any(rel == p or rel.endswith(p) for p in self.forbidden_overwrite_paths)


def filter_blocks_for_delivery(blocks: dict[str, str], repo_root) -> tuple[dict[str, str], list[str]]:
    """Drop forbidden overwrites of large existing files; return filtered blocks and dropped paths."""
    from pathlib import Path

    from gateway_enhancement_agent.file_blocks import normalize_repo_path

    delivery = DeliveryConfig.from_env()
    repo = Path(repo_root)
    filtered: dict[str, str] = {}
    dropped: list[str] = []
    for raw_rel, content in blocks.items():
        rel = normalize_repo_path(raw_rel)
        if delivery.is_forbidden_overwrite(rel) and (repo / rel).is_file():
            dropped.append(rel)
            continue
        filtered[rel] = content
    return filtered, dropped

