from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.target_inventory import TargetInventory


def test_backlog_sync_and_scheduled(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    store = BacklogStore()
    gap = GapItem(
        gap_id="inv-000",
        title="DELETE /v1/responses/{id}",
        source="api_inventory",
        priority=1,
        score=10,
        route="/v1/responses/{id}",
        coverage="Gap",
    )
    store.sync_from_matrix([gap], cycle_id=1)
    store.mark_scheduled("inv-000", cycle_id=1)
    data = store.load()
    item = data["items"]["inv-000"]
    assert item["status"] == "scheduled"
    assert item["times_scheduled"] == 1


def test_backlog_reconcile_reopens_closed_without_dedicated_test(tmp_path, monkeypatch, mock_target_repo) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DELIVERY_MODE", "tests_first")
    monkeypatch.setenv("DELIVERY_CONFIG", "delivery_tests_first.json")
    store = BacklogStore()
    store.save(
        {
            "version": 1,
            "items": {
                "inv-000": {
                    "gap_id": "inv-000",
                    "title": "DELETE /v1/responses/{id}",
                    "status": "closed",
                    "closed_reason": "route_already_covered_in_tests",
                }
            },
        }
    )
    inv = TargetInventory(mock_target_repo).parse_inventory_gaps()
    changes = store.reconcile_with_inventory(inv, mock_target_repo, cycle_id=1)
    assert any("inv-000" in c and "reopened" in c for c in changes)
    item = store.load()["items"]["inv-000"]
    assert item["status"] == "open"
    assert item["title"] == f"{inv[0].method} {inv[0].route}"


def test_deferred_gap_excluded_from_analyzer(tmp_path, monkeypatch, mock_target_repo):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    store = BacklogStore()
    store.save(
        {
            "version": 1,
            "items": {
            "inv-000": {
                "gap_id": "inv-000",
                "title": "POST /v1/chat/completions",
                "status": "deferred",
            }
            },
        }
    )
    matrix = GapAnalyzer().build_matrix()
    ids = [g.gap_id for g in matrix]
    assert "inv-000" not in ids
