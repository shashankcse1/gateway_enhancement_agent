from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.gap_models import GapItem


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
