"""Map API inventory gaps to owning router modules (not always gateway.py)."""

from __future__ import annotations

import re

from gateway_enhancement_agent.gap_analyzer import GapItem
from gateway_enhancement_agent.gap_intelligence import parse_route

# Longest-prefix wins when matching route paths.
_ROUTE_PREFIX_MODULES: list[tuple[str, str]] = [
    ("/v1/vector_stores", "backend/app/routers/gateway_rag.py"),
    ("/v1/rag", "backend/app/routers/gateway_rag.py"),
    ("/gateway/vector-stores", "backend/app/routers/gateway_memory.py"),
    ("/gateway/memory", "backend/app/routers/gateway_memory.py"),
    ("/gateway/rag", "backend/app/routers/gateway_rag.py"),
]

_HANDLER_ANCHOR_RE = re.compile(
    r'@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']',
    re.I,
)


def normalize_route_path(path: str) -> str:
    p = path.strip()
    if not p.startswith("/"):
        p = f"/{p}"
    return p.rstrip("/") or "/"


def router_module_for_route(route: str | None) -> str | None:
    if not route:
        return None
    _method, path = parse_route(route)
    path = normalize_route_path(path)
    best: tuple[str, str] | None = None
    for prefix, module in _ROUTE_PREFIX_MODULES:
        norm_prefix = normalize_route_path(prefix)
        if path == norm_prefix or path.startswith(norm_prefix + "/"):
            if best is None or len(norm_prefix) > len(best[0]):
                best = (norm_prefix, module)
    return best[1] if best else None


def router_module_for_gap(gap: GapItem) -> str:
    """Prefer route map, then inventory section header, else gateway monolith."""
    mapped = router_module_for_route(gap.route)
    if mapped:
        return mapped
    section = (gap.rationale or "").lower()
    if "gateway_rag" in section:
        return "backend/app/routers/gateway_rag.py"
    if "gateway_memory" in section:
        return "backend/app/routers/gateway_memory.py"
    return "backend/app/routers/gateway.py"


def path_hints_for_gap(gap: GapItem, worker_id: str | None = None) -> list[str]:
    """Route-aware context/edit targets for implement workers."""
    router = router_module_for_gap(gap)
    test_path = None
    if gap.route:
        from gateway_enhancement_agent.delivery_config import suggest_test_path

        test_path = suggest_test_path(gap.gap_id, gap.route)

    common = [
        "backend/AGENTS.md",
        router,
        "backend/docs/governance/api-inventory-and-ui-map.md",
    ]
    if test_path:
        common.append(test_path)

    if worker_id == "backend_tests":
        from gateway_enhancement_agent.gap_intelligence import pick_test_template

        template = pick_test_template(gap.route or gap.title)
        return [template, "backend/tests/test_gateway_inference.py", *( [test_path] if test_path else [])]
    if worker_id == "backend_contract":
        return [router, "backend/AGENTS.md", "backend/docs/governance/api-inventory-and-ui-map.md"]
    if worker_id == "frontend_ui":
        return [
            "frontend/app.js",
            "frontend/views/routing-gateway.html",
            "backend/docs/governance/ui-api-design-coverage-map.md",
        ]
    if worker_id == "governance_docs":
        return [
            "backend/docs/governance/api-inventory-and-ui-map.md",
            "backend/docs/governance/ui-api-design-coverage-map.md",
            "backend/docs/security/residual-and-accepted-risk-register.md",
        ]
    return common


def ui_anchors_for_gap(gap: GapItem) -> list[str]:
    """Return one tight anchor region for frontend UI snippet extraction (not whole hub blocks)."""
    route_l = (gap.route or gap.title or "").lower()
    if "vector_store" in route_l:
        method = route_l.split(None, 1)[0] if route_l else ""
        if "{store_id}" in route_l or "/store_id" in route_l:
            return [
                "loadGatewayVectorStoreContext",
                "testGatewayVectorStoreHealth",
            ]
        if method == "post":
            return [
                "addGatewayVectorStoreRow",
                "gatewayVectorStoreConfigTable",
            ]
        return [
            "loadOrchestrationVectorStoreOptions",
            "gatewayVectorStoreConfigTable",
        ]
    if gap.route:
        _method, path = parse_route(gap.route)
        slug = path.strip("/").replace("/", "_").replace("-", "_").replace("{", "").replace("}", "")
        if slug:
            return [slug, path.strip()]
    if gap.title:
        return [gap.title[:48]]
    return handler_anchors_for_gap(gap)[:2]


def ui_append_hint_for_gap(gap: GapItem) -> str | None:
    """Optional append-only anchor hint for frontend_ui worker prompts."""
    route_l = (gap.route or gap.title or "").lower()
    if "vector_store" in route_l and "{store_id}" in route_l:
        return (
            "Append a small OpenAI-compatible store inspector panel after "
            "`testGatewayVectorStoreHealth` wiring in routing-gateway.html; "
            "add a `loadOpenAiVectorStoreDetail(storeId)` handler in app.js near "
            "`loadGatewayVectorStoreContext`."
        )
    if "vector_store" in route_l and route_l.startswith("post "):
        return (
            "Wire a minimal create-store operator form near `addGatewayVectorStoreRow`; "
            "handler should POST to `/v1/vector_stores` near existing vector store helpers."
        )
    return None


def handler_anchors_for_gap(gap: GapItem) -> list[str]:
    """Anchors for scoped snippet extraction inside router modules."""
    anchors: list[str] = []
    if gap.route:
        _method, path = parse_route(gap.route)
        anchors.append(path.strip())
        anchors.append(f'"{path.strip()}"')
        anchors.append(f"'{path.strip()}'")
        slug = path.strip("/").replace("/", "_").replace("-", "_")
        if slug:
            anchors.append(slug)
    if gap.title:
        anchors.append(gap.title)
    return anchors
