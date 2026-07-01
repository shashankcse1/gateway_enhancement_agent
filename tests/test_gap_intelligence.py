from __future__ import annotations

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.gap_intelligence import (
    normalize_test_blocks,
    parse_route,
    route_mentioned_in_content,
    scaffold_auth_test,
)
from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.test_repair import structured_pytest_failure


def test_parse_route_with_method() -> None:
    method, path = parse_route("DELETE /v1/responses/{id}")
    assert method == "DELETE"
    assert path == "/v1/responses/{id}"


def test_route_mentioned_in_test_content() -> None:
    content = 'client.delete("/v1/responses/abc", headers=ADMIN_HEADERS)'
    assert route_mentioned_in_content(content, "DELETE", "/v1/responses/{id}")


def test_normalize_test_blocks_renames_misnamed_file() -> None:
    blocks = {"backend/tests/test_gateway_v1_vector_stores_store_id.py": "assert True\n"}
    out = normalize_test_blocks(blocks, gap_id="inv-004", route="GET /v1/vector_stores/{store_id}")
    assert list(out.keys()) == ["backend/tests/test_gateway_get_v1_vector_stores_store_id.py"]


def test_scaffold_auth_test_uses_status_in() -> None:
    gap = GapItem(
        gap_id="inv-001",
        title="DELETE /v1/responses/{id}",
        source="api_inventory",
        priority=1,
        score=10,
        route="DELETE /v1/responses/{id}",
        coverage="Gap",
    )
    text = scaffold_auth_test(gap, "backend/tests/test_gateway_delete_v1_responses_id.py")
    assert "assert response.status_code in" in text
    assert "_ensure_tenant" not in text


def test_structured_pytest_failure_extracts_assertion() -> None:
    raw = "FAILED tests/x.py::test_a\nassert 404 == 200\nE   assert 404 == 200"
    out = structured_pytest_failure(raw, "")
    assert "404" in out


def test_backlog_auto_defer_after_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    store = BacklogStore()
    store.sync_from_matrix(
        [
            GapItem(
                gap_id="inv-001",
                title="DELETE /v1/responses/{id}",
                source="api_inventory",
                priority=1,
                score=10,
                route="/v1/responses/{id}",
                coverage="Gap",
            )
        ],
        cycle_id=1,
    )
    store.record_validation_failure("inv-001", 1, reason="pytest")
    assert not store.should_auto_defer("inv-001")
    store.record_validation_failure("inv-001", 2, reason="pytest")
    assert store.should_auto_defer("inv-001")
    store.mark_deferred("inv-001", 2, reason="pytest failed 2x")
    assert "inv-001" in store.deferred_ids()


def test_analyzer_skips_covered_vector_store_route(mock_target_repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    rag = mock_target_repo / "backend/tests/test_gateway_rag.py"
    rag.parent.mkdir(parents=True, exist_ok=True)
    rag.write_text(
        'client.get(f"/v1/vector_stores/{store_id}", headers=ADMIN_HEADERS)\n',
        encoding="utf-8",
    )
    inv = mock_target_repo / "backend/docs/governance/api-inventory-and-ui-map.md"
    inv.write_text(
        """### `app/routers/gateway.py`

| Method | Route | UI Coverage | Notes |
| ------ | ----- | ----------- | ----- |
| GET | `/v1/vector_stores/{store_id}` | Partial | missing UI |
| DELETE | `/v1/responses/{id}` | Gap | not wired |
""",
        encoding="utf-8",
    )
    analyzer = GapAnalyzer()
    closed = analyzer.close_covered_gaps_in_backlog(cycle_id=9)
    assert any("inv-" in gid for gid in closed)
    top = analyzer.top_gap()
    assert top is not None
    assert "vector_stores" not in top.title.lower() or top.coverage == "Gap"
