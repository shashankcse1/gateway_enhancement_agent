"""Web research via free public docs + local rule-based extraction (no Ollama)."""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

from gateway_enhancement_agent.config import load_json, runtime_dir
from gateway_enhancement_agent.local_capability_extractor import extract_capabilities_from_text


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._chunks))


@dataclass
class ResearchConfig:
    enabled: bool
    cache_ttl_hours: int
    max_pages_per_competitor: int
    max_chars_per_page: int
    user_agent: str
    extraction_mode: str
    allowed_domains: list[str]
    competitors: list[dict[str, Any]]

    @classmethod
    def from_env(cls) -> ResearchConfig:
        raw = load_json("competitor_research.json")
        env_on = os.environ.get("COMPETITOR_WEB_RESEARCH", "").strip().lower()
        enabled = bool(raw.get("enabled", True))
        if env_on in {"0", "false", "no"}:
            enabled = False
        elif env_on in {"1", "true", "yes"}:
            enabled = True
        return cls(
            enabled=enabled,
            cache_ttl_hours=int(os.environ.get("COMPETITOR_RESEARCH_CACHE_HOURS", raw.get("cache_ttl_hours", 168))),
            max_pages_per_competitor=int(raw.get("max_pages_per_competitor", 3)),
            max_chars_per_page=int(raw.get("max_chars_per_page", 12000)),
            user_agent=raw.get("user_agent", "GatewayEnhancementAgent/1.0"),
            extraction_mode=os.environ.get("COMPETITOR_RESEARCH_MODE", raw.get("extraction_mode", "local")),
            allowed_domains=list(raw.get("allowed_domains", [])),
            competitors=list(raw.get("competitors", [])),
        )


@dataclass
class PageFetch:
    url: str
    ok: bool
    chars: int = 0
    error: str | None = None


@dataclass
class CompetitorResearchResult:
    competitor_id: str
    name: str
    pages: list[PageFetch] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class CompetitorWebResearcher:
    """Fetches free public documentation and extracts capabilities locally (no Ollama)."""

    def __init__(self, config: ResearchConfig | None = None) -> None:
        self.config = config or ResearchConfig.from_env()
        self.cache_path = runtime_dir() / "competitor_research_cache.json"
        self._seed_caps = self._load_seed_capabilities()

    def _load_seed_capabilities(self) -> dict[str, list[dict[str, Any]]]:
        raw = load_json("competitors.json")
        out: dict[str, list[dict[str, Any]]] = {}
        for entry in raw.get("competitors", []):
            out[entry["id"]] = list(entry.get("capabilities", []))
        return out

    def load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {"version": 1, "updated_at": None, "extraction_mode": "local", "competitors": {}}
        return json.loads(self.cache_path.read_text(encoding="utf-8"))

    def save_cache(self, payload: dict[str, Any]) -> None:
        self.cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def cache_stale(self) -> bool:
        from gateway_enhancement_agent.delivery_config import DeliveryConfig

        delivery = DeliveryConfig.from_env()
        cache = self.load_cache()
        updated = cache.get("updated_at")
        if not updated:
            return True
        try:
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            return True
        hours = delivery.refresh_competitor_research_hours
        return datetime.now(timezone.utc) - ts > timedelta(hours=hours)

    def refresh(self, *, force: bool = False) -> dict[str, Any]:
        if not self.config.enabled:
            return {"refreshed": False, "skipped": "Web research disabled"}
        if not force and not self.cache_stale():
            cache = self.load_cache()
            return {
                "refreshed": False,
                "skipped": "Cache still fresh",
                "updated_at": cache.get("updated_at"),
                "competitor_count": len(cache.get("competitors", {})),
                "extraction_mode": cache.get("extraction_mode", "local"),
            }

        results: list[CompetitorResearchResult] = []
        with ThreadPoolExecutor(max_workers=min(4, len(self.config.competitors) or 1)) as pool:
            futures = {
                pool.submit(self._research_competitor, entry): entry for entry in self.config.competitors
            }
            for future in as_completed(futures):
                entry = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        CompetitorResearchResult(
                            competitor_id=entry.get("id", "unknown"),
                            name=entry.get("name", "unknown"),
                            error=str(exc),
                        )
                    )

        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "extraction_mode": self.config.extraction_mode,
            "provider": "local_free_sources",
            "competitors": {
                r.competitor_id: {
                    "name": r.name,
                    "pages": [{"url": p.url, "ok": p.ok, "chars": p.chars, "error": p.error} for p in r.pages],
                    "capabilities": r.capabilities,
                    "error": r.error,
                }
                for r in results
            },
        }
        self.save_cache(payload)
        web_caps = sum(len(c.get("capabilities", [])) for c in payload["competitors"].values())
        return {
            "refreshed": True,
            "updated_at": payload["updated_at"],
            "extraction_mode": self.config.extraction_mode,
            "provider": "local_free_sources",
            "competitor_count": len(results),
            "web_capabilities_found": web_caps,
            "results": [
                {
                    "competitor_id": r.competitor_id,
                    "pages_ok": sum(1 for p in r.pages if p.ok),
                    "capabilities": len(r.capabilities),
                    "error": r.error,
                }
                for r in results
            ],
        }

    def web_capabilities(self) -> dict[str, list[dict[str, Any]]]:
        cache = self.load_cache()
        out: dict[str, list[dict[str, Any]]] = {}
        for cid, entry in cache.get("competitors", {}).items():
            out[cid] = list(entry.get("capabilities", []))
        return out

    def report_markdown(self) -> str:
        cache = self.load_cache()
        lines = [
            "# Competitor Web Research Cache",
            "",
            f"Updated: {cache.get('updated_at', '—')}",
            f"Provider: {cache.get('provider', 'local_free_sources')} (free public docs, local extraction)",
            f"Extraction: {cache.get('extraction_mode', 'local')}",
            "",
            "| Competitor | Web capabilities | Pages OK |",
            "| --- | --- | --- |",
        ]
        for cid, entry in cache.get("competitors", {}).items():
            caps = len(entry.get("capabilities", []))
            pages_ok = sum(1 for p in entry.get("pages", []) if p.get("ok"))
            lines.append(f"| {entry.get('name', cid)} | {caps} | {pages_ok} |")
        return "\n".join(lines) + "\n"

    def _research_competitor(self, entry: dict[str, Any]) -> CompetitorResearchResult:
        cid = entry["id"]
        name = entry.get("name", cid)
        urls = list(entry.get("urls", []))[: self.config.max_pages_per_competitor]
        pages: list[PageFetch] = []
        combined: list[str] = []
        for url in urls:
            if not self._is_allowed_free_url(url):
                pages.append(PageFetch(url=url, ok=False, error="URL not in allowed free-source domains"))
                continue
            text, fetch = self._fetch_page(url)
            pages.append(fetch)
            if text:
                combined.append(f"## Source: {url}\n\n{text}")
        if not combined:
            return CompetitorResearchResult(
                competitor_id=cid,
                name=name,
                pages=pages,
                error="No pages fetched from free sources",
            )
        blob = "\n\n".join(combined)[: self.config.max_chars_per_page * self.config.max_pages_per_competitor]
        capabilities = extract_capabilities_from_text(
            competitor_id=cid,
            name=name,
            text=blob,
            seed_capabilities=self._seed_caps.get(cid, []),
            keyword_signals=list(entry.get("keyword_signals", [])),
        )
        return CompetitorResearchResult(
            competitor_id=cid,
            name=name,
            pages=pages,
            capabilities=capabilities,
        )

    def _is_allowed_free_url(self, url: str) -> bool:
        if not url.startswith("https://"):
            return False
        host = urllib.parse.urlparse(url).netloc.lower()
        if not self.config.allowed_domains:
            return True
        return any(host == d or host.endswith(f".{d}") for d in self.config.allowed_domains)

    def _fetch_page(self, url: str) -> tuple[str | None, PageFetch]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.config.user_agent})
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                raw = resp.read()
            html = raw.decode("utf-8", errors="replace")
            parser = _TextExtractor()
            parser.feed(html)
            text = parser.text()[: self.config.max_chars_per_page]
            return text, PageFetch(url=url, ok=True, chars=len(text))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return None, PageFetch(url=url, ok=False, error=str(exc))


def maybe_refresh_competitor_research() -> dict[str, Any]:
    return CompetitorWebResearcher().refresh(force=False)
