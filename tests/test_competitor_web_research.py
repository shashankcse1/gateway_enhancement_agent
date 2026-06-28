from __future__ import annotations

from unittest.mock import patch

from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.competitor_web_research import CompetitorWebResearcher, PageFetch, ResearchConfig
from gateway_enhancement_agent.local_capability_extractor import extract_capabilities_from_text


def test_local_extractor_matches_seed_and_routes() -> None:
    text = "Supports /v1/chat/completions with virtual key budget limits and caching."
    caps = extract_capabilities_from_text(
        competitor_id="litellm",
        name="LiteLLM",
        text=text,
        seed_capabilities=[
            {
                "id": "virtual_keys_budgets",
                "label": "Virtual keys and budget guardrails",
                "priority": 1,
                "route_hints": ["/keys", "/cost"],
            }
        ],
        keyword_signals=[{"id": "caching", "label": "Response caching", "priority": 2, "keywords": ["caching"]}],
    )
    ids = {c["id"] for c in caps}
    assert "web_virtual_keys_budgets" in ids
    assert "web_caching" in ids
    assert any("/v1/chat/completions" in c.get("route_hints", []) for c in caps)


def test_web_research_uses_local_extractor(mock_target_repo) -> None:
    cfg = ResearchConfig(
        enabled=True,
        cache_ttl_hours=168,
        max_pages_per_competitor=1,
        max_chars_per_page=5000,
        user_agent="test",
        extraction_mode="local",
        allowed_domains=["docs.helicone.ai"],
        competitors=[
            {
                "id": "helicone",
                "name": "Helicone",
                "urls": ["https://docs.helicone.ai/getting-started/quick-start"],
                "keyword_signals": [
                    {"id": "cost_analytics", "label": "Cost analytics", "priority": 2, "keywords": ["cost analytics"]}
                ],
            }
        ],
    )
    researcher = CompetitorWebResearcher(cfg)
    with patch.object(
        researcher,
        "_fetch_page",
        return_value=(
            "Helicone cost analytics dashboard for /cost/timeseries observability",
            PageFetch(url="https://docs.helicone.ai/getting-started/quick-start", ok=True, chars=60),
        ),
    ):
        result = researcher.refresh(force=True)
    assert result["refreshed"] is True
    assert result["provider"] == "local_free_sources"
    assert result["extraction_mode"] == "local"
    caps = researcher.web_capabilities().get("helicone", [])
    assert any(c["source"] == "web_free" for c in caps)


def test_web_research_rejects_non_allowlisted_url(mock_target_repo) -> None:
    cfg = ResearchConfig(
        enabled=True,
        cache_ttl_hours=168,
        max_pages_per_competitor=1,
        max_chars_per_page=1000,
        user_agent="test",
        extraction_mode="local",
        allowed_domains=["docs.helicone.ai"],
        competitors=[
            {"id": "helicone", "name": "Helicone", "urls": ["https://paid-api.example.com/docs"]},
        ],
    )
    result = CompetitorWebResearcher(cfg).refresh(force=True)
    assert result["refreshed"] is True
    entry = CompetitorWebResearcher(cfg).load_cache()["competitors"]["helicone"]
    assert entry["pages"][0]["ok"] is False


def test_registry_merges_web_capabilities(mock_target_repo) -> None:
    researcher = CompetitorWebResearcher(
        ResearchConfig(
            enabled=True,
            cache_ttl_hours=168,
            max_pages_per_competitor=1,
            max_chars_per_page=1000,
            user_agent="test",
            extraction_mode="local",
            allowed_domains=[],
            competitors=[],
        )
    )
    researcher.save_cache(
        {
            "version": 1,
            "updated_at": "2026-06-28T00:00:00+00:00",
            "extraction_mode": "local",
            "provider": "local_free_sources",
            "competitors": {
                "helicone": {
                    "name": "Helicone",
                    "pages": [],
                    "capabilities": [
                        {
                            "id": "web_new_feature",
                            "label": "New web-only feature",
                            "priority": 2,
                            "route_hints": ["/v1/new"],
                            "source": "web_free",
                        }
                    ],
                }
            },
        }
    )
    snap = CompetitorRegistry().snapshot()
    helicone = next(c for c in snap["competitors"] if c["id"] == "helicone")
    assert any(cap["source"] == "web" for cap in helicone["capabilities"])
