"""Rule-based capability extraction from free public docs — no Ollama, no cloud API."""

from __future__ import annotations

import re
from typing import Any

ROUTE_RE = re.compile(
    r"(?P<route>/((?:v1|gateway|rag|cost|observability|keys)[/\w\-{}.*]+))",
    re.IGNORECASE,
)


def extract_capabilities_from_text(
    *,
    competitor_id: str,
    name: str,
    text: str,
    seed_capabilities: list[dict[str, Any]],
    keyword_signals: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Match seed capabilities and keyword signals against fetched doc text."""
    lower = text.lower()
    found: dict[str, dict[str, Any]] = {}

    for seed in seed_capabilities:
        cap_id = str(seed.get("id", ""))
        if not cap_id:
            continue
        terms = _terms_for_capability(seed)
        if _any_term_present(lower, terms):
            found[cap_id] = {
                "id": f"web_{cap_id}",
                "label": str(seed.get("label", cap_id)),
                "priority": int(seed.get("priority", 3)),
                "route_hints": list(seed.get("route_hints", [])),
                "source": "web_free",
                "evidence": "seed_match",
            }

    for signal in keyword_signals or []:
        sid = str(signal.get("id", ""))
        label = str(signal.get("label", sid))
        keywords = [str(k).lower() for k in signal.get("keywords", []) if k]
        if not sid or not _any_term_present(lower, keywords):
            continue
        if sid not in found:
            found[sid] = {
                "id": f"web_{sid}",
                "label": label,
                "priority": int(signal.get("priority", 3)),
                "route_hints": list(signal.get("route_hints", [])),
                "source": "web_free",
                "evidence": "keyword_signal",
            }

    for route in _extract_routes(text):
        key = _slug(route)
        if key in found:
            hints = found[key].setdefault("route_hints", [])
            if route not in hints:
                hints.append(route)
            continue
        # Only add novel routes when they look like API paths
        if route.startswith("/v1/") or route.startswith("/gateway/"):
            found[f"route_{key}"] = {
                "id": f"web_route_{key}",
                "label": f"Documented route {route}",
                "priority": 3,
                "route_hints": [route],
                "source": "web_free",
                "evidence": "route_parse",
            }

    return sorted(found.values(), key=lambda c: (c["priority"], c["id"]))


def _terms_for_capability(cap: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    label = str(cap.get("label", "")).lower()
    if label:
        terms.append(label)
        terms.extend(label.split())
    for hint in cap.get("route_hints", []):
        h = str(hint).lower().strip("/")
        if h:
            terms.append(h)
            terms.append(str(hint).lower())
    cap_id = str(cap.get("id", "")).replace("_", " ").lower()
    if cap_id:
        terms.append(cap_id)
    return [t for t in terms if len(t) >= 4]


def _any_term_present(lower_text: str, terms: list[str]) -> bool:
    return any(t in lower_text for t in terms if t)


def _extract_routes(text: str) -> list[str]:
    routes: list[str] = []
    for match in ROUTE_RE.finditer(text):
        route = match.group("route").split("?")[0].rstrip(".,;)")
        if route not in routes and len(route) <= 80:
            routes.append(route)
    return routes


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:48]
