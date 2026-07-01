"""Prioritize implementation gaps from inventory + competitor matrix."""

from __future__ import annotations

from typing import Any

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.gap_intelligence import (
    adjust_gap_score,
    find_covering_test_files,
    is_route_covered_in_tests,
    load_gap_intelligence_config,
    normalize_test_blocks,
    parse_route,
    route_mentioned_in_content,
    scaffold_auth_test,
)
from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.target_inventory import TargetInventory


class GapAnalyzer:
    def __init__(self) -> None:
        self.inventory = TargetInventory()
        self.competitors = CompetitorRegistry()
        self.backlog = BacklogStore()
        self.repo = self.inventory.repo

    def _close_covered_gaps(self, matrix: list[GapItem]) -> list[GapItem]:
        cfg = load_gap_intelligence_config()
        if not cfg.get("auto_close_covered_routes", True):
            return matrix
        kept: list[GapItem] = []
        for gap in matrix:
            route = gap.route or gap.title
            if is_route_covered_in_tests(route, self.repo):
                continue
            kept.append(gap)
        return kept

    def close_covered_gaps_in_backlog(self, cycle_id: int) -> list[str]:
        """Mark inventory gaps as closed when tests already cover the route."""
        closed: list[str] = []
        cfg = load_gap_intelligence_config()
        if not cfg.get("auto_close_covered_routes", True):
            return closed
        inv = self.inventory.parse_inventory_gaps()
        deferred = self.backlog.deferred_ids()
        already_closed = self.backlog.closed_ids()
        for idx, gap in enumerate(inv):
            gap_id = f"inv-{idx:03d}"
            if gap_id in deferred or gap_id in already_closed:
                continue
            route = f"{gap.method} {gap.route}"
            if not is_route_covered_in_tests(route, self.repo):
                continue
            files = find_covering_test_files(self.repo, gap.method, gap.route)
            self.backlog.mark_covered(gap_id, cycle_id, covering_files=files)
            closed.append(gap_id)
        return closed

    def _apply_intelligence_scoring(self, matrix: list[GapItem]) -> None:
        for gap in matrix:
            failures = self.backlog.validation_failure_count(gap.gap_id)
            gap.score = adjust_gap_score(gap, self.repo, validation_failures=failures)

    def _match_capabilities(self, route: str | None) -> tuple[list[str], list[str]]:
        if not route:
            return [], []
        competitor_ids: list[str] = []
        capabilities: list[str] = []
        for profile in self.competitors.load_profiles():
            for cap in profile.capabilities:
                if any(hint in route for hint in cap.route_hints):
                    competitor_ids.append(profile.id)
                    capabilities.append(cap.id)
        return sorted(set(competitor_ids)), capabilities

    def _base_score(self, coverage: str | None, priority: int) -> int:
        if coverage and coverage.lower() == "gap":
            return 10
        if coverage and coverage.lower() == "partial":
            return 20
        return 10 + priority * 10

    def build_matrix(self) -> list[GapItem]:
        items: list[GapItem] = []
        deferred = self.backlog.deferred_ids()
        closed = self.backlog.closed_ids()
        inv = self.inventory.parse_inventory_gaps()
        for idx, gap in enumerate(inv):
            gap_id = f"inv-{idx:03d}"
            if gap_id in deferred or gap_id in closed:
                continue
            notes = (gap.notes or "").lower()
            if "deprecated" in notes:
                continue
            priority = 1 if gap.coverage.lower() == "gap" else 2
            comp_ids, cap_ids = self._match_capabilities(gap.route)
            score = self._base_score(gap.coverage, priority)
            if gap.coverage and gap.coverage.lower() == "partial" and gap.route:
                score -= 8
            if gap.coverage and gap.coverage.lower() == "gap" and comp_ids:
                score -= 3
            if any(
                cap.priority == 1
                for profile in self.competitors.load_profiles()
                for cap in profile.capabilities
                if cap.id in cap_ids
            ):
                score -= 5
            items.append(
                GapItem(
                    gap_id=gap_id,
                    title=f"{gap.method} {gap.route}",
                    source="api_inventory",
                    priority=priority,
                    score=score,
                    route=gap.route,
                    coverage=gap.coverage,
                    competitor_ids=comp_ids,
                    related_capabilities=cap_ids,
                    rationale=gap.notes or f"API inventory marks {gap.coverage} in {gap.section}",
                )
            )

        for theme_idx, theme in enumerate(self.competitors.optimization_themes()):
            items.append(
                GapItem(
                    gap_id=f"opt-{theme_idx:03d}",
                    title=theme,
                    source="optimization_theme",
                    priority=3,
                    score=30 + theme_idx,
                    route=None,
                    coverage=None,
                    competitor_ids=["market"],
                    rationale="Documented post-parity optimization theme",
                )
            )

        by_title: dict[str, GapItem] = {}
        for item in items:
            if item.gap_id in deferred:
                continue
            existing = by_title.get(item.title)
            if existing is None or item.score < existing.score:
                by_title[item.title] = item

        ranked = sorted(by_title.values(), key=lambda g: (g.score, g.gap_id))
        self._apply_staleness_boost(ranked)
        self._apply_intelligence_scoring(ranked)
        ranked = sorted(ranked, key=lambda g: (g.score, g.gap_id))
        return self._close_covered_gaps(ranked)

    def _apply_staleness_boost(self, matrix: list[GapItem]) -> None:
        data = self.backlog.load()
        items = data.get("items", {})
        for gap in matrix:
            meta = items.get(gap.gap_id, {})
            if int(meta.get("times_scheduled", 0)) >= 3 and meta.get("status") != "closed":
                gap.score = max(1, gap.score - 3)

    def top_gap(self) -> GapItem | None:
        matrix = self.build_matrix()
        return matrix[0] if matrix else None

    def report_markdown(self) -> str:
        matrix = self.build_matrix()
        lines = [
            "# Gateway Gap Matrix",
            "",
            f"Total prioritized items: **{len(matrix)}**",
            "",
            "| Score | ID | Source | Item | Competitors |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in matrix[:30]:
            comps = ", ".join(item.competitor_ids) or "—"
            lines.append(
                f"| {item.score} | `{item.gap_id}` | {item.source} | {item.title} | {comps} |"
            )
        if len(matrix) > 30:
            lines.append(f"\n_…and {len(matrix) - 30} more items._")
        return "\n".join(lines) + "\n"

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {
                "gap_id": g.gap_id,
                "title": g.title,
                "source": g.source,
                "priority": g.priority,
                "score": g.score,
                "route": g.route,
                "coverage": g.coverage,
                "competitor_ids": g.competitor_ids,
                "related_capabilities": g.related_capabilities,
                "rationale": g.rationale,
            }
            for g in self.build_matrix()
        ]
