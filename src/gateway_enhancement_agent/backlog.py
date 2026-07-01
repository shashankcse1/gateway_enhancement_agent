"""Persistent enhancement backlog across SDLC cycles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import runtime_dir
from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.target_inventory import InventoryGap


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

    def mark_deferred(self, gap_id: str, cycle_id: int, *, reason: str) -> None:
        data = self.load()
        item = data.setdefault("items", {}).get(gap_id)
        if not item:
            item = {"gap_id": gap_id, "title": gap_id}
        item["status"] = "deferred"
        item["deferred_cycle"] = cycle_id
        item["deferred_at"] = _utc_now()
        item["deferred_reason"] = reason[:500]
        data.setdefault("items", {})[gap_id] = item
        data["updated_at"] = _utc_now()
        self.save(data)

    def mark_covered(self, gap_id: str, cycle_id: int, *, covering_files: list[str]) -> None:
        data = self.load()
        item = data.setdefault("items", {}).get(gap_id)
        if not item:
            return
        item["status"] = "closed"
        item["closed_cycle"] = cycle_id
        item["closed_at"] = _utc_now()
        item["closed_reason"] = "route_already_covered_in_tests"
        item["covering_test_files"] = covering_files
        data["updated_at"] = _utc_now()
        self.save(data)

    def record_validation_failure(self, gap_id: str, cycle_id: int, *, reason: str) -> int:
        data = self.load()
        item = data.setdefault("items", {}).get(gap_id)
        if not item:
            item = {"gap_id": gap_id, "title": gap_id}
        count = int(item.get("validation_failures", 0)) + 1
        item["validation_failures"] = count
        item["last_validation_failure_cycle"] = cycle_id
        item["last_validation_failure_reason"] = reason[:500]
        data.setdefault("items", {})[gap_id] = item
        data["updated_at"] = _utc_now()
        self.save(data)
        return count

    def validation_failure_count(self, gap_id: str) -> int:
        data = self.load()
        item = data.get("items", {}).get(gap_id, {})
        return int(item.get("validation_failures", 0))

    def reconcile_with_inventory(
        self,
        inventory_gaps: list[InventoryGap],
        repo,
        *,
        cycle_id: int = 0,
    ) -> list[str]:
        """Align inv-* backlog rows with current inventory; reopen falsely closed gaps."""
        from pathlib import Path

        from gateway_enhancement_agent.delivery_config import DeliveryConfig
        from gateway_enhancement_agent.gap_intelligence import (
            is_gap_covered_for_delivery,
            load_gap_intelligence_config,
        )

        root = Path(repo)
        data = self.load()
        items: dict[str, Any] = data.setdefault("items", {})
        changes: list[str] = []
        cfg = load_gap_intelligence_config()
        max_failures = int(cfg.get("max_validation_failures", 2))
        tests_first = DeliveryConfig.from_env().tests_first

        for idx, gap in enumerate(inventory_gaps):
            gap_id = f"inv-{idx:03d}"
            route = f"{gap.method} {gap.route}"
            item = items.get(gap_id)
            if item is None:
                continue
            if item.get("title") != route or item.get("route") != gap.route:
                item["title"] = route
                item["route"] = gap.route
                item["coverage"] = gap.coverage
                changes.append(f"{gap_id}: synced title/route")
            if tests_first and item.get("status") == "closed":
                if not is_gap_covered_for_delivery(gap_id, route, root):
                    item["status"] = "open"
                    for key in (
                        "closed_reason",
                        "closed_cycle",
                        "closed_at",
                        "covering_test_files",
                        "commit_sha",
                    ):
                        item.pop(key, None)
                    changes.append(f"{gap_id}: reopened (dedicated test missing)")
            if (
                cfg.get("auto_defer_on_max_failures", True)
                and item.get("status") not in ("deferred", "closed")
                and int(item.get("validation_failures", 0)) >= max_failures
            ):
                item["status"] = "deferred"
                item.setdefault(
                    "deferred_reason",
                    f"auto-deferred after {item['validation_failures']} validation failure(s)",
                )
                item["deferred_cycle"] = item.get("deferred_cycle", cycle_id)
                changes.append(f"{gap_id}: auto-deferred")
        if changes:
            data["updated_at"] = _utc_now()
            self.save(data)
        return changes

    def should_auto_defer(self, gap_id: str) -> bool:
        from gateway_enhancement_agent.gap_intelligence import load_gap_intelligence_config

        cfg = load_gap_intelligence_config()
        if not cfg.get("auto_defer_on_max_failures", True):
            return False
        limit = int(cfg.get("max_validation_failures", 2))
        return self.validation_failure_count(gap_id) >= limit

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
