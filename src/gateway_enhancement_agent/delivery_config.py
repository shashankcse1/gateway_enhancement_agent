"""Focused delivery settings for reliable autonomous code commits."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gateway_enhancement_agent.config import load_json


@dataclass
class DeliveryConfig:
    delivery_mode: str
    serial_llm: bool
    max_parallel_workers: int
    refresh_competitor_research_hours: int
    allowed_write_prefixes: list[str]
    forbidden_path_prefixes: list[str]
    forbidden_overwrite_paths: list[str]
    prefer_implement_workers: list[str]
    min_lines_large_files: dict[str, int]
    max_files_per_cycle: int
    new_files_only: bool

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
            delivery_mode=str(os.environ.get("DELIVERY_MODE", raw.get("delivery_mode", "full"))),
            serial_llm=serial,
            max_parallel_workers=max_workers,
            refresh_competitor_research_hours=int(
                os.environ.get("COMPETITOR_RESEARCH_REFRESH_HOURS", raw.get("refresh_competitor_research_hours", 24))
            ),
            allowed_write_prefixes=list(raw.get("allowed_write_prefixes", [])),
            forbidden_path_prefixes=list(raw.get("forbidden_path_prefixes", [])),
            forbidden_overwrite_paths=list(raw.get("forbidden_overwrite_paths", [])),
            prefer_implement_workers=list(raw.get("prefer_implement_workers", [])),
            min_lines_large_files=dict(raw.get("min_lines_large_files", {})),
            max_files_per_cycle=int(raw.get("max_files_per_cycle", 0)),
            new_files_only=bool(raw.get("new_files_only", False)),
        )

    @property
    def tests_first(self) -> bool:
        return self.delivery_mode.strip().lower() == "tests_first"

    def is_forbidden_overwrite(self, rel: str) -> bool:
        return any(rel == p or rel.endswith(p) for p in self.forbidden_overwrite_paths)

    def is_allowed_path(self, rel: str) -> bool:
        if not self.tests_first:
            return True
        if self.forbidden_path_prefixes and any(rel.startswith(p) for p in self.forbidden_path_prefixes):
            return False
        if self.allowed_write_prefixes:
            return any(rel.startswith(p) for p in self.allowed_write_prefixes)
        return True


def filter_blocks_for_delivery(blocks: dict[str, str], repo_root) -> tuple[dict[str, str], list[str]]:
    """Drop disallowed paths; return filtered blocks and dropped paths."""
    from pathlib import Path

    from gateway_enhancement_agent.file_blocks import normalize_repo_path

    delivery = DeliveryConfig.from_env()
    repo = Path(repo_root)
    filtered: dict[str, str] = {}
    dropped: list[str] = []
    for raw_rel, content in blocks.items():
        rel = normalize_repo_path(raw_rel)
        reason: str | None = None
        if not delivery.is_allowed_path(rel):
            reason = "path not allowed for delivery mode"
        elif delivery.is_forbidden_overwrite(rel) and (repo / rel).is_file():
            reason = "forbidden overwrite"
        elif delivery.new_files_only and delivery.tests_first and (repo / rel).is_file():
            allow = os.environ.get("AGENT_ALLOW_TEST_OVERWRITE", "").strip() in {"1", "true", "yes"}
            if not (allow and rel.startswith("backend/tests/test_gateway_")):
                reason = "new_files_only — file already exists"
        if reason:
            dropped.append(f"{rel} ({reason})")
            continue
        filtered[rel] = content

    if delivery.tests_first and delivery.max_files_per_cycle > 0 and len(filtered) > delivery.max_files_per_cycle:
        keep = sorted(filtered.keys())[: delivery.max_files_per_cycle]
        for rel in sorted(filtered.keys())[delivery.max_files_per_cycle :]:
            dropped.append(f"{rel} (max_files_per_cycle={delivery.max_files_per_cycle})")
        filtered = {k: filtered[k] for k in keep}

    return filtered, dropped


def suggest_test_path(gap_id: str, route: str | None) -> str:
    if route:
        parts = route.strip().split(None, 1)
        method = parts[0].lower() if parts else ""
        path_part = parts[1].strip("/") if len(parts) > 1 else ""
        slug = path_part.lower().replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")
        if method:
            slug = f"{method}_{slug}" if slug else method
        return f"backend/tests/test_gateway_{slug}.py"
    slug = gap_id.lower().replace("-", "_")
    return f"backend/tests/test_gap_{slug}.py"
