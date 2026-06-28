"""Map competitor capabilities to gateway route/inventory coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.target_inventory import TargetInventory


@dataclass
class CapabilityCoverageRow:
    capability_id: str
    label: str
    competitor_id: str
    competitor_name: str
    priority: int
    status: str  # full | partial | gap | unknown
    matched_routes: list[str]
    notes: str


class CapabilityCoverage:
    def __init__(self) -> None:
        self.registry = CompetitorRegistry()
        self.inventory = TargetInventory()

    def build(self) -> list[CapabilityCoverageRow]:
        inv_rows = self.inventory.list_inventory_rows()
        results: list[CapabilityCoverageRow] = []
        for profile in self.registry.load_profiles():
            for cap in profile.capabilities:
                hints = cap.route_hints
                matched = [
                    f"{method} {route}"
                    for method, route, coverage, _ in inv_rows
                    if any(hint in route for hint in hints)
                ]
                coverages = [
                    coverage
                    for method, route, coverage, _ in inv_rows
                    if any(hint in route for hint in hints)
                ]
                if not hints:
                    status, notes = "unknown", "No route_hints configured"
                elif not matched:
                    status, notes = "unknown", "No inventory rows matched route_hints"
                elif any(c.lower() == "gap" for c in coverages):
                    status, notes = "gap", "At least one matched route is Gap in inventory"
                elif any(c.lower() == "partial" for c in coverages):
                    status, notes = "partial", "Matched routes are Partial in inventory"
                else:
                    status, notes = "full", "All matched routes are Full in inventory"
                results.append(
                    CapabilityCoverageRow(
                        capability_id=cap.id,
                        label=cap.label,
                        competitor_id=profile.id,
                        competitor_name=profile.name,
                        priority=cap.priority,
                        status=status,
                        matched_routes=matched,
                        notes=notes,
                    )
                )
        results.sort(key=lambda r: (r.priority, r.status != "full", r.capability_id))
        return results

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {
                "capability_id": r.capability_id,
                "label": r.label,
                "competitor_id": r.competitor_id,
                "competitor_name": r.competitor_name,
                "priority": r.priority,
                "status": r.status,
                "matched_routes": r.matched_routes,
                "notes": r.notes,
            }
            for r in self.build()
        ]

    def report_markdown(self) -> str:
        rows = self.build()
        lines = [
            "# Competitor Capability Coverage",
            "",
            "| Priority | Competitor | Capability | Status | Matched routes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in rows:
            routes = ", ".join(r.matched_routes[:3]) or "—"
            if len(r.matched_routes) > 3:
                routes += f" (+{len(r.matched_routes) - 3})"
            lines.append(
                f"| {r.priority} | {r.competitor_name} | {r.label} | {r.status} | {routes} |"
            )
        return "\n".join(lines) + "\n"
