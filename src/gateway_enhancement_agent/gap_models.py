"""Shared gap model types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GapItem:
    gap_id: str
    title: str
    source: str
    priority: int
    score: int
    route: str | None
    coverage: str | None
    competitor_ids: list[str] = field(default_factory=list)
    related_capabilities: list[str] = field(default_factory=list)
    rationale: str = ""


def gap_to_dict(gap: GapItem) -> dict:
    return {
        "gap_id": gap.gap_id,
        "title": gap.title,
        "source": gap.source,
        "priority": gap.priority,
        "score": gap.score,
        "route": gap.route,
        "coverage": gap.coverage,
        "competitor_ids": list(gap.competitor_ids),
        "related_capabilities": list(gap.related_capabilities),
        "rationale": gap.rationale,
    }


def gap_from_dict(data: dict) -> GapItem:
    return GapItem(
        gap_id=str(data["gap_id"]),
        title=str(data.get("title", data["gap_id"])),
        source=str(data.get("source", "api_inventory")),
        priority=int(data.get("priority", 2)),
        score=int(data.get("score", 10)),
        route=data.get("route"),
        coverage=data.get("coverage"),
        competitor_ids=list(data.get("competitor_ids", [])),
        related_capabilities=list(data.get("related_capabilities", [])),
        rationale=str(data.get("rationale", "")),
    )
