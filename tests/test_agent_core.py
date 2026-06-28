from __future__ import annotations

import json

from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.target_inventory import TargetInventory


def test_target_inventory_finds_gaps(mock_target_repo) -> None:
    inv = TargetInventory(mock_target_repo)
    snap = inv.snapshot()
    assert snap["gateway_route_count"] == 2
    assert snap["partial_gap_count"] == 2
    assert snap["agents_contract"] is True


def test_gap_analyzer_prioritizes_gap_over_partial(mock_target_repo) -> None:
    top = GapAnalyzer().top_gap()
    assert top is not None
    assert top.coverage == "Gap"
    assert top.score <= 20


def test_competitor_registry_loads_profiles(mock_target_repo) -> None:
    reg = CompetitorRegistry()
    snap = reg.snapshot()
    assert snap["competitor_count"] >= 4
    assert snap["capability_count"] >= 10


def test_sdlc_pipeline_writes_artifacts(mock_target_repo, monkeypatch) -> None:
    from gateway_enhancement_agent.sdlc_pipeline import SDLCPipeline
    from gateway_enhancement_agent.state_store import StateStore

    monkeypatch.setenv("LOCAL_LLM_AUTO_IMPLEMENT", "0")
    monkeypatch.setenv("AGENT_FULLY_AUTONOMOUS", "0")
    store = StateStore()
    cycle = SDLCPipeline(store).run_cycle(skip_validation=True)
    assert cycle.status == "completed"
    art = store.cycle_dir(cycle.cycle_id)
    assert (art / "gap_matrix.json").exists()
    assert (art / "capability_coverage.json").exists()
    assert (art / "cycle_summary.json").exists()
    assert (art / "agent_work_order.md").exists()
    assert (art / "implementation_report.json").exists()
    matrix = json.loads((art / "gap_matrix.json").read_text(encoding="utf-8"))
    assert len(matrix) >= 1
