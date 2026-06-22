"""Read-only scan of target gateway repo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import target_repo

GATEWAY_ROUTE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', re.I)
INVENTORY_ROW = re.compile(
    r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|\s*(Full|Partial|Gap)\s*\|",
    re.I,
)


@dataclass
class InventoryGap:
    method: str
    route: str
    coverage: str
    notes: str
    section: str


class TargetInventory:
    def __init__(self, repo: Path | None = None) -> None:
        self.repo = repo or target_repo()

    def _backend(self) -> Path:
        backend = self.repo / "backend"
        return backend if backend.is_dir() else self.repo

    def gateway_routes(self) -> int:
        gateway_py = self._backend() / "app/routers/gateway.py"
        if not gateway_py.exists():
            return 0
        return len(GATEWAY_ROUTE.findall(gateway_py.read_text(encoding="utf-8")))

    def gateway_tests(self) -> list[str]:
        tests = self._backend() / "tests"
        if not tests.is_dir():
            return []
        return sorted(p.name for p in tests.glob("test_gateway*.py"))

    def agents_contract_exists(self) -> bool:
        return (self._backend() / "AGENTS.md").exists()

    def parse_inventory_gaps(self) -> list[InventoryGap]:
        for rel in (
            "docs/governance/api-inventory-and-ui-map.md",
            "backend/docs/governance/api-inventory-and-ui-map.md",
        ):
            path = self.repo / rel
            if path.exists():
                return self._parse_inventory_file(path)
        return []

    def _parse_inventory_file(self, path: Path) -> list[InventoryGap]:
        gaps: list[InventoryGap] = []
        section = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("### "):
                section = line.removeprefix("### ").strip()
                continue
            if "gateway" not in section.lower() and "/gateway" not in line and "/v1/" not in line:
                continue
            match = INVENTORY_ROW.match(line)
            if not match:
                continue
            method, route, coverage = match.group(1).upper(), match.group(2), match.group(3)
            if coverage.lower() == "full":
                continue
            parts = [p.strip() for p in line.split("|")]
            notes = parts[4] if len(parts) >= 5 else ""
            gaps.append(
                InventoryGap(method=method, route=route, coverage=coverage, notes=notes, section=section)
            )
        return gaps

    def snapshot(self) -> dict[str, Any]:
        gaps = self.parse_inventory_gaps()
        return {
            "target_repo": str(self.repo),
            "gateway_route_count": self.gateway_routes(),
            "gateway_test_files": self.gateway_tests(),
            "agents_contract": self.agents_contract_exists(),
            "partial_or_gap_endpoints": [
                {
                    "method": g.method,
                    "route": g.route,
                    "coverage": g.coverage,
                    "notes": g.notes,
                    "section": g.section,
                }
                for g in gaps
            ],
            "partial_gap_count": len(gaps),
        }
