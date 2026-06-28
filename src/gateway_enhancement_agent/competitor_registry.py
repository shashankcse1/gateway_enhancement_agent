"""Local + web competitor profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.competitor_web_research import CompetitorWebResearcher
from gateway_enhancement_agent.config import load_json, target_repo


@dataclass
class CompetitorCapability:
    id: str
    label: str
    priority: int
    competitor_id: str
    competitor_name: str
    route_hints: list[str]
    source: str = "config"


@dataclass
class CompetitorProfile:
    id: str
    name: str
    capabilities: list[CompetitorCapability]
    reference_excerpts: list[str]
    web_sources: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.web_sources is None:
            self.web_sources = []


class CompetitorRegistry:
    def __init__(self) -> None:
        self.raw: dict[str, Any] = load_json("competitors.json")
        self._repo = target_repo()
        self._researcher = CompetitorWebResearcher()

    def _read_reference(self, rel_path: str) -> str | None:
        for base in self._candidate_roots():
            full = base / rel_path
            if not full.exists():
                full = base / "backend" / rel_path
            if full.exists():
                try:
                    return full.read_text(encoding="utf-8")[:4000]
                except OSError:
                    continue
        return None

    def _candidate_roots(self) -> list[Path]:
        roots = [self._repo]
        mirror = os.environ.get("TARGET_REPO_MIRROR", "").strip().strip('"').strip("'")
        if mirror:
            roots.append(Path(mirror).expanduser().resolve())
        return roots

    def _web_capabilities_for(self, competitor_id: str) -> list[dict[str, Any]]:
        return self._researcher.web_capabilities().get(competitor_id, [])

    def load_profiles(self) -> list[CompetitorProfile]:
        profiles: list[CompetitorProfile] = []
        for entry in self.raw.get("competitors", []):
            excerpts: list[str] = []
            for doc in entry.get("reference_docs", []):
                text = self._read_reference(doc)
                if text:
                    excerpts.append(f"### {doc}\n\n{text}")
            seen_ids: set[str] = set()
            caps: list[CompetitorCapability] = []
            for c in entry.get("capabilities", []):
                cap_id = c["id"]
                seen_ids.add(cap_id)
                caps.append(
                    CompetitorCapability(
                        id=cap_id,
                        label=c["label"],
                        priority=int(c.get("priority", 3)),
                        competitor_id=entry["id"],
                        competitor_name=entry["name"],
                        route_hints=list(c.get("route_hints", [])),
                        source="config",
                    )
                )
            web_sources: list[str] = []
            cache_entry = self._researcher.load_cache().get("competitors", {}).get(entry["id"], {})
            for page in cache_entry.get("pages", []):
                if page.get("ok"):
                    web_sources.append(page.get("url", ""))
            for wc in self._web_capabilities_for(entry["id"]):
                cap_id = wc.get("id", "")
                if cap_id in seen_ids:
                    continue
                seen_ids.add(cap_id)
                caps.append(
                    CompetitorCapability(
                        id=cap_id,
                        label=str(wc.get("label", cap_id)),
                        priority=int(wc.get("priority", 3)),
                        competitor_id=entry["id"],
                        competitor_name=entry["name"],
                        route_hints=list(wc.get("route_hints", [])),
                        source="web",
                    )
                )
            profiles.append(
                CompetitorProfile(
                    id=entry["id"],
                    name=entry["name"],
                    capabilities=caps,
                    reference_excerpts=excerpts,
                    web_sources=[u for u in web_sources if u],
                )
            )
        return profiles

    def optimization_themes(self) -> list[str]:
        return list(self.raw.get("optimization_themes", []))

    def snapshot(self) -> dict[str, Any]:
        profiles = self.load_profiles()
        web_count = sum(1 for p in profiles for c in p.capabilities if c.source == "web")
        cache = self._researcher.load_cache()
        return {
            "target_repo": str(self._repo),
            "competitor_count": len(profiles),
            "capability_count": sum(len(p.capabilities) for p in profiles),
            "web_research_updated_at": cache.get("updated_at"),
            "web_capability_count": web_count,
            "optimization_themes": self.optimization_themes(),
            "competitors": [
                {
                    "id": p.id,
                    "name": p.name,
                    "capabilities": [
                        {"id": c.id, "label": c.label, "priority": c.priority, "source": c.source}
                        for c in p.capabilities
                    ],
                    "has_reference_docs": bool(p.reference_excerpts),
                    "web_sources": p.web_sources,
                }
                for p in profiles
            ],
        }
