"""Persistent enhancement backlog across SDLC cycles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import runtime_dir
from gateway_enhancement_agent.gap_models import GapItem


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class BacklogItem:
    gap_id: str
    title: str
    status: str = "open"
    source: str = ""
    route: str | None = None
    coverage: str | None = None
    competitor_ids: list[str] = field(default_factory=list)
    related_capabilities: list[str] = field(default_factory=list)
    score: int = 100
    first_seen_cycle: int = 0
    last_seen_cycle: int = 0
    times_scheduled: int = 0
    last_scheduled_cycle: int | None = None


class BacklogStore:
    def __init__(self) -> None:
        self.path = runtime_dir() / "backlog.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "items": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def sync_from_matrix(self, matrix: list[GapItem], cycle_id: int) -> None:
        data = self.load()
        items: dict[str, Any] = data.setdefault("items", {})
        seen_ids = {g.gap_id for g in matrix}
        for gap in matrix:
            existing = items.get(gap.gap_id, {})
            if existing.get("status") == "deferred":
                existing["last_seen_cycle"] = cycle_id
                items[gap.gap_id] = existing
                continue
            items[gap.gap_id] = {
                "gap_id": gap.gap_id,
                "title": gap.title,
                "status": existing.get("status", "open"),
                "source": gap.source,
                "route": gap.route,
                "coverage": gap.coverage,
                "competitor_ids": gap.competitor_ids,
                "related_capabilities": gap.related_capabilities,
                "score": gap.score,
                "first_seen_cycle": existing.get("first_seen_cycle", cycle_id),
                "last_seen_cycle": cycle_id,
                "times_scheduled": existing.get("times_scheduled", 0),
                "last_scheduled_cycle": existing.get("last_scheduled_cycle"),
            }
        for gap_id, item in list(items.items()):
            if gap_id not in seen_ids and item.get("status") == "open":
                item["status"] = "stale"
        data["updated_at"] = _utc_now()
        self.save(data)

    def mark_scheduled(self, gap_id: str, cycle_id: int) -> None:
        data = self.load()
        item = data.setdefault("items", {}).get(gap_id)
        if not item:
            return
        item["status"] = "scheduled"
        item["times_scheduled"] = int(item.get("times_scheduled", 0)) + 1
        item["last_scheduled_cycle"] = cycle_id
        data["updated_at"] = _utc_now()
        self.save(data)

    def deferred_ids(self) -> set[str]:
        data = self.load()
        return {
            gap_id
            for gap_id, item in data.get("items", {}).items()
            if item.get("status") == "deferred"
        }

    def closed_ids(self) -> set[str]:
        data = self.load()
        return {
            gap_id
            for gap_id, item in data.get("items", {}).items()
            if item.get("status") == "closed"
        }

    def mark_closed(self, gap_id: str, cycle_id: int, *, commit_sha: str | None = None) -> None:
        data = self.load()
        item = data.setdefault("items", {}).get(gap_id)
        if not item:
            return
        item["status"] = "closed"
        item["closed_cycle"] = cycle_id
        item["closed_at"] = _utc_now()
        if commit_sha:
            item["commit_sha"] = commit_sha
        data["updated_at"] = _utc_now()
        self.save(data)

    def report_markdown(self) -> str:
        data = self.load()
        items = list(data.get("items", {}).values())
        items.sort(key=lambda i: (i.get("score", 100), i.get("gap_id", "")))
        lines = [
            "# Enhancement Backlog",
            "",
            f"Items: **{len(items)}** (updated {data.get('updated_at', '—')})",
            "",
            "| Score | Status | ID | Title | Scheduled |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in items[:40]:
            lines.append(
                f"| {item.get('score', '—')} | {item.get('status')} | `{item.get('gap_id')}` "
                f"| {item.get('title', '')[:50]} | {item.get('times_scheduled', 0)}x |"
            )
        return "\n".join(lines) + "\n"
