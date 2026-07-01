from __future__ import annotations

from gateway_enhancement_agent.gap_models import GapItem, gap_from_dict, gap_to_dict
from gateway_enhancement_agent.sdlc_pipeline import SDLCPipeline
from gateway_enhancement_agent.state_store import CycleState


def test_gap_snapshot_roundtrip() -> None:
    gap = GapItem(
        gap_id="inv-003",
        title="GET /v1/vector_stores",
        source="api_inventory",
        priority=2,
        score=20,
        route="GET /v1/vector_stores",
        coverage="Partial",
        rationale="Dedicated test file missing",
    )
    restored = gap_from_dict(gap_to_dict(gap))
    assert restored.gap_id == gap.gap_id
    assert restored.title == gap.title
    assert restored.route == gap.route


def test_active_gap_uses_snapshot_when_matrix_moves_on(mock_target_repo) -> None:
    pipeline = SDLCPipeline()
    cycle = CycleState(
        cycle_id=99,
        started_at="2026-01-01T00:00:00+00:00",
        phase="merge",
        target_repo=str(mock_target_repo),
        active_gap_id="inv-003",
        metadata={
            "active_gap_snapshot": gap_to_dict(
                GapItem(
                    gap_id="inv-003",
                    title="GET /v1/vector_stores",
                    source="api_inventory",
                    priority=2,
                    score=20,
                    route="GET /v1/vector_stores",
                    coverage="Partial",
                )
            )
        },
    )
    gap = pipeline._active_gap(cycle)
    assert gap is not None
    assert gap.gap_id == "inv-003"
    assert gap.title == "GET /v1/vector_stores"
