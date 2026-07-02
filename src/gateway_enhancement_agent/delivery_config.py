"""Focused delivery settings for reliable autonomous code commits."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gateway_enhancement_agent.config import load_json
from gateway_enhancement_agent.path_utils import normalize_repo_path

_GOVERNANCE_PREFIX = "backend/docs/governance/"
_TESTS_PREFIX = "backend/tests/"


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
    implementation_waves: list[list[str]]
    rotate_implementation_waves: bool
    min_lines_large_files: dict[str, int]
    large_file_line_threshold: int
    max_files_per_cycle: int
    new_files_only: bool

    @classmethod
    def from_env(cls) -> DeliveryConfig:
        try:
            config_name = os.environ.get("DELIVERY_CONFIG", "delivery.json")
            raw = load_json(config_name)
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
            implementation_waves=[list(w) for w in raw.get("implementation_waves", [])],
            rotate_implementation_waves=bool(raw.get("rotate_implementation_waves", False)),
            min_lines_large_files=dict(raw.get("min_lines_large_files", {})),
            large_file_line_threshold=int(raw.get("large_file_line_threshold", 500)),
            max_files_per_cycle=int(raw.get("max_files_per_cycle", 0)),
            new_files_only=bool(raw.get("new_files_only", False)),
        )

    @property
    def tests_first(self) -> bool:
        return self.delivery_mode.strip().lower() == "tests_first"

    @property
    def full(self) -> bool:
        return self.delivery_mode.strip().lower() == "full"

    def implement_workers_for_cycle(self, cycle_id: int) -> list[str]:
        if self.full and self.implementation_waves and self.rotate_implementation_waves:
            wave = self.implementation_waves[(max(1, cycle_id) - 1) % len(self.implementation_waves)]
            return wave
        if self.prefer_implement_workers:
            return self.prefer_implement_workers
        return []

    def implement_workers_for_gap(self, cycle_id: int, gap, repo) -> list[str]:
        """Route Partial gaps with existing tests to UI/governance waves."""
        from pathlib import Path

        from gateway_enhancement_agent.gap_intelligence import dedicated_test_file_exists

        if self.full and gap is not None and getattr(gap, "coverage", ""):
            if gap.coverage.lower() == "partial" and dedicated_test_file_exists(
                gap.gap_id, gap.route, Path(repo)
            ):
                ui_wave = ["frontend_ui", "governance_docs"]
                if self.implementation_waves:
                    for wave in self.implementation_waves:
                        if "frontend_ui" in wave:
                            return [w for w in wave if w in {"frontend_ui", "governance_docs"}] or ui_wave
                return ui_wave
        return self.implement_workers_for_cycle(cycle_id)

    def is_forbidden_overwrite(self, rel: str) -> bool:
        return any(rel == p or rel.endswith(p) for p in self.forbidden_overwrite_paths)

    def line_count_threshold(self, rel: str) -> int:
        return int(self.min_lines_large_files.get(rel, self.large_file_line_threshold))

    def is_large_existing_file(self, rel: str, repo_root) -> bool:
        from pathlib import Path

        path = Path(repo_root) / rel
        if not path.is_file():
            return False
        try:
            lines = len(path.read_text(encoding="utf-8").splitlines())
        except OSError:
            return False
        return lines >= self.line_count_threshold(rel)

    def requires_patch_mode(self, rel: str, repo_root) -> bool:
        if self.is_forbidden_overwrite(rel):
            return True
        return self.is_large_existing_file(rel, repo_root)

    def is_truncating_overwrite(self, rel: str, content: str, repo_root) -> bool:
        """True when content shrinks a protected path enough to look like a full rewrite."""
        if not self.is_forbidden_overwrite(rel):
            return False
        from pathlib import Path

        path = Path(repo_root) / rel
        if not path.is_file():
            return False
        try:
            existing_lines = len(path.read_text(encoding="utf-8").splitlines())
        except OSError:
            return False
        new_lines = len(content.splitlines()) or (1 if content.strip() else 0)
        if existing_lines < 50:
            return new_lines < max(1, existing_lines // 2)
        return new_lines < int(existing_lines * 0.75)

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

    from gateway_enhancement_agent.path_utils import normalize_repo_path

    delivery = DeliveryConfig.from_env()
    repo = Path(repo_root)
    filtered: dict[str, str] = {}
    dropped: list[str] = []
    for raw_rel, content in blocks.items():
        rel = normalize_repo_path(raw_rel)
        reason: str | None = None
        if not delivery.is_allowed_path(rel):
            reason = "path not allowed for delivery mode"
        elif delivery.is_truncating_overwrite(rel, content, repo):
            reason = "forbidden overwrite"
        elif delivery.new_files_only and delivery.tests_first and (repo / rel).is_file():
            allow = os.environ.get("AGENT_ALLOW_TEST_OVERWRITE", "").strip() in {"1", "true", "yes"}
            if not (allow and rel.startswith("backend/tests/test_gateway_")):
                reason = "new_files_only — file already exists"
        if reason:
            dropped.append(f"{rel} ({reason})")
            continue
        filtered[rel] = content

    if delivery.max_files_per_cycle > 0 and len(filtered) > delivery.max_files_per_cycle:
        keep = sorted(filtered.keys())[: delivery.max_files_per_cycle]
        for rel in sorted(filtered.keys())[delivery.max_files_per_cycle :]:
            dropped.append(f"{rel} (max_files_per_cycle={delivery.max_files_per_cycle})")
        filtered = {k: filtered[k] for k in keep}

    return filtered, dropped


def should_skip_review_stage(paths: list[str]) -> bool:
    """Skip mandatory role-lens review for governance-only or test-only changes."""
    from gateway_enhancement_agent.path_utils import normalize_repo_path

    if not paths:
        return False
    normalized = [normalize_repo_path(p) for p in paths]
    if all(p.startswith("backend/docs/governance/") for p in normalized):
        return True
    if all(_is_test_only_path(p) for p in normalized):
        return True
    return False


def _is_test_only_path(rel: str) -> bool:
    if "/tests/" in rel or rel.startswith("tests/"):
        return True
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("test_") and name.endswith(".py")


def suggest_test_path(gap_id: str, route: str | None) -> str:
    if route:
        text = route.strip()
        parts = text.split(None, 1)
        if len(parts) == 2 and parts[0].upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            method = parts[0].lower()
            path_part = parts[1].strip("/")
        else:
            method = "get"
            path_part = text.lstrip("/")
        slug = path_part.lower().replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")
        slug = f"{method}_{slug}" if slug else method
        return f"backend/tests/test_gateway_{slug}.py"
    slug = gap_id.lower().replace("-", "_")
    return f"backend/tests/test_gap_{slug}.py"
