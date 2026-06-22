"""Local competitor profiles — no network calls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import load_json, target_repo


@dataclass
class CompetitorCapability:
    id: str
    label: str
    priority: int
    competitor_id: str
    competitor_name: str


@dataclass
class CompetitorProfile:
    id: str
    name: str
    capabilities: list[CompetitorCapability]
    reference_excerpts: list[str]


class CompetitorRegistry:
    def __init__(self) -> None:
        self.raw: dict[str, Any] = load_json("competitors.json")
        self._repo = target_repo()

    def _read_reference(self, rel_path: str) -> str | None:
        full = self._repo / rel_path
        if not full.exists():
            alt = self._repo / "backend" / rel_path
            if alt.exists():
                full = alt
            else:
                return None
        return full.read_text(encoding="utf-8")[:4000]

    def load_profiles(self) -> list[CompetitorProfile]:
        profiles: list[CompetitorProfile] = []
        for entry in self.raw.get("competitors", []):
            excerpts: list[str] = []
            for doc in entry.get("reference_docs", []):
                text = self._read_reference(doc)
                if text:
                    excerpts.append(f"### {doc}\n\n{text}")
            caps = [
                CompetitorCapability(
                    id=c["id"],
                    label=c["label"],
                    priority=int(c.get("priority", 3)),
                    competitor_id=entry["id"],
                    competitor_name=entry["name"],
                )
                for c in entry.get("capabilities", [])
            ]
            profiles.append(
                CompetitorProfile(
                    id=entry["id"],
                    name=entry["name"],
                    capabilities=caps,
                    reference_excerpts=excerpts,
                )
            )
        return profiles

    def optimization_themes(self) -> list[str]:
        return list(self.raw.get("optimization_themes", []))

    def snapshot(self) -> dict[str, Any]:
        profiles = self.load_profiles()
        return {
            "target_repo": str(self._repo),
            "competitor_count": len(profiles),
            "capability_count": sum(len(p.capabilities) for p in profiles),
            "optimization_themes": self.optimization_themes(),
            "competitors": [
                {
                    "id": p.id,
                    "name": p.name,
                    "capabilities": [
                        {"id": c.id, "label": c.label, "priority": c.priority}
                        for c in p.capabilities
                    ],
                    "has_reference_docs": bool(p.reference_excerpts),
                }
                for p in profiles
            ],
        }
