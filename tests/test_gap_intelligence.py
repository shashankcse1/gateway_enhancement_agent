from __future__ import annotations

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.gap_intelligence import (
    is_gap_covered_for_delivery,
    normalize_test_blocks,
    parse_route,
    route_mentioned_in_content,
    scaffold_auth_test,
)
from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.test_repair import structured_pytest_failure


def test_drop_unchanged_blocks(tmp_path) -> None:
    from gateway_enhancement_agent.file_blocks import drop_unchanged_blocks

    path = tmp_path / "backend/tests/test_x.py"
    path.parent.mkdir(parents=True)
    path.write_text("assert True\n", encoding="utf-8")
    changed, dropped = drop_unchanged_blocks(
        tmp_path,
        {
            "backend/tests/test_x.py": "assert True\n",
            "backend/tests/test_new.py": "assert 1\n",
        },
    )
    assert "backend/tests/test_new.py" in changed
    assert "backend/tests/test_x.py" not in changed
    assert any("no-op" in d for d in dropped)


def test_full_mode_gap_auto_close_when_dedicated_test_exists(mock_target_repo, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    target = mock_target_repo / "backend/tests/test_gateway_delete_v1_responses_id.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    assert is_gap_covered_for_delivery(
        "inv-001",
        "DELETE /v1/responses/{id}",
        mock_target_repo,
        coverage="Gap",
    )


def test_full_mode_partial_stays_open_when_test_exists(mock_target_repo, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    target = mock_target_repo / "backend/tests/test_gateway_get_v1_vector_stores.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    assert not is_gap_covered_for_delivery(
        "inv-003",
        "GET /v1/vector_stores",
        mock_target_repo,
        coverage="Partial",
    )


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


def test_full_mode_keeps_partial_inventory_gaps_open(mock_target_repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DELIVERY_CONFIG", raising=False)
    rag = mock_target_repo / "backend/tests/test_gateway_rag.py"
    rag.parent.mkdir(parents=True, exist_ok=True)
    rag.write_text('client.get("/v1/vector_stores", headers=ADMIN_HEADERS)\n', encoding="utf-8")
    assert is_gap_covered_for_delivery(
        "inv-001", "POST /v1/chat/completions", mock_target_repo, coverage="Partial"
    ) is False
    matrix = GapAnalyzer().build_matrix()
    assert any(g.gap_id.startswith("inv-") for g in matrix)


    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DELIVERY_MODE", "tests_first")
    monkeypatch.setenv("DELIVERY_CONFIG", "delivery_tests_first.json")
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
    store = BacklogStore()
    store.save(
        {
            "version": 1,
            "items": {
                "inv-000": {
                    "gap_id": "inv-000",
                    "title": "GET /v1/vector_stores/{store_id}",
                    "status": "closed",
                    "closed_reason": "route_already_covered_in_tests",
                }
            },
        }
    )
    analyzer = GapAnalyzer()
    closed = analyzer.close_covered_gaps_in_backlog(cycle_id=9)
    assert "inv-000" not in closed
    matrix = analyzer.build_matrix()
    assert any(g.gap_id == "inv-000" for g in matrix)
    top = analyzer.top_gap()
    assert top is not None
    assert "vector_stores" in top.title.lower() or top.coverage == "Gap"
