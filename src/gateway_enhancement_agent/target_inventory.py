"""Read-only scan of target gateway repo."""

from __future__ import annotations

import os
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
        mirror = os.environ.get("TARGET_REPO_MIRROR", "").strip().strip('"').strip("'")
        self.mirror = Path(mirror).expanduser().resolve() if mirror else None

    def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            if self.mirror is None:
                return None
            rel = None
            for base in (self.repo,):
                try:
                    rel = path.relative_to(base)
                    break
                except ValueError:
                    continue
            if rel is None:
                return None
            alt = self.mirror / rel
            if alt.exists():
                return alt.read_text(encoding="utf-8")
            return None

    def _backend(self) -> Path:
        backend = self.repo / "backend"
        return backend if backend.is_dir() else self.repo

    def gateway_routes(self) -> int:
        gateway_py = self._backend() / "app/routers/gateway.py"
        text = self._read_text(gateway_py)
        if not text:
            return 0
        return len(GATEWAY_ROUTE.findall(text))

    def gateway_tests(self) -> list[str]:
        tests = self._backend() / "tests"
        if not tests.is_dir():
            return []
        return sorted(p.name for p in tests.glob("test_gateway*.py"))

    def parse_inventory_gaps(self) -> list[InventoryGap]:
        rels = (
            "backend/docs/governance/api-inventory-and-ui-map.md",
            "docs/governance/api-inventory-and-ui-map.md",
        )
        paths: list[Path] = []
        for rel in rels:
            paths.append(self.repo / rel)
            if self.mirror:
                paths.append(self.mirror / rel)
        for path in paths:
            gaps = self._parse_inventory_file(path)
            if gaps:
                return gaps
        return []

    def agents_contract_exists(self) -> bool:
        path = self._backend() / "AGENTS.md"
        return self._read_text(path) is not None

    def _parse_inventory_file(self, path: Path) -> list[InventoryGap]:
        text = self._read_text(path)
        if not text:
            return []
        gaps: list[InventoryGap] = []
        section = ""
        for line in text.splitlines():
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
