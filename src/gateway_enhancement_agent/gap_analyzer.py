"""Prioritize implementation gaps from inventory + competitor matrix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.target_inventory import TargetInventory


@dataclass
class GapItem:
    gap_id: str
    title: str
    source: str
    priority: int
    route: str | None
    coverage: str | None
    competitor_id: str | None
    rationale: str


class GapAnalyzer:
    def __init__(self) -> None:
        self.inventory = TargetInventory()
        self.competitors = CompetitorRegistry()

    def build_matrix(self) -> list[GapItem]:
        items: list[GapItem] = []
        inv = self.inventory.parse_inventory_gaps()
        for idx, gap in enumerate(inv):
            priority = 1 if gap.coverage.lower() == "gap" else 2
            items.append(
                GapItem(
                    gap_id=f"inv-{idx:03d}",
                    title=f"{gap.method} {gap.route}",
                    source="api_inventory",
                    priority=priority,
                    route=gap.route,
                    coverage=gap.coverage,
                    competitor_id=None,
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
                    route=None,
                    coverage=None,
                    competitor_id="market",
                    rationale="Documented post-parity optimization theme",
                )
            )

        # De-duplicate by title, keep highest priority (lowest number)
        by_title: dict[str, GapItem] = {}
        for item in items:
            existing = by_title.get(item.title)
            if existing is None or item.priority < existing.priority:
                by_title[item.title] = item

        ranked = sorted(by_title.values(), key=lambda g: (g.priority, g.gap_id))
        return ranked

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
            "| Priority | ID | Source | Item | Route |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in matrix[:30]:
            lines.append(
                f"| {item.priority} | `{item.gap_id}` | {item.source} | {item.title} | {item.route or '—'} |"
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
                "route": g.route,
                "coverage": g.coverage,
                "competitor_id": g.competitor_id,
                "rationale": g.rationale,
            }
            for g in self.build_matrix()
        ]
