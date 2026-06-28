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
