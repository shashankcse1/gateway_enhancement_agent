from __future__ import annotations

from unittest.mock import MagicMock

from gateway_enhancement_agent.gap_analyzer import GapItem
from gateway_enhancement_agent.parallel_orchestrator import ParallelConfig, ParallelOrchestrator, WorkerSpec


def _gap() -> GapItem:
    return GapItem(
        gap_id="inv-001",
        title="DELETE /v1/responses/{id}",
        score=10,
        priority=1,
        source="inventory",
        route="DELETE /v1/responses/{id}",
        coverage="Gap",
        rationale="missing",
        competitor_ids=[],
        related_capabilities=[],
    )


def test_parallel_orchestrator_merges_non_conflicting_workers(mock_target_repo, tmp_path) -> None:
    cfg = ParallelConfig(
        enabled=True,
        max_workers=2,
        synthesizer_enabled=True,
        run_review_stage=False,
        workers=[
            WorkerSpec("backend_contract", "Backend", "backend", ["backend/app/routers/gateway.py"], stage="implement"),
            WorkerSpec("backend_tests", "Tests", "tests", ["backend/tests/test_gateway_routes.py"], stage="implement"),
        ],
    )
    client = MagicMock()
    client.chat.side_effect = [
        '```file:backend/app/routers/gateway.py\n@router.delete("/v1/responses/{id}")\n```',
        '```file:backend/tests/test_gateway_routes.py\ndef test_delete():\n    assert True\n```',
    ]
    artifact_dir = tmp_path / "cycle-0001"
    artifact_dir.mkdir()
    result = ParallelOrchestrator(None, cfg, client).run(
        gap=_gap(),
        cycle_id=1,
        design_brief="# brief",
        shared_context="ctx",
        artifact_dir=artifact_dir,
    )
    assert len(result.subagents) == 2
    assert result.merged_blocks["backend/app/routers/gateway.py"].startswith("@router")
    assert "test_delete" in result.merged_blocks["backend/tests/test_gateway_routes.py"]
    assert (artifact_dir / "subagents" / "backend_contract.md").exists()


def test_parallel_orchestrator_uses_synthesizer_on_conflict(mock_target_repo, tmp_path) -> None:
    cfg = ParallelConfig(
        enabled=True,
        max_workers=2,
        synthesizer_enabled=True,
        run_review_stage=False,
        workers=[
            WorkerSpec("backend_contract", "Backend", "backend", [], stage="implement"),
            WorkerSpec("backend_tests", "Tests", "tests", [], stage="implement"),
        ],
    )
    client = MagicMock()
    client.chat.side_effect = [
        '```file:backend/app/routers/gateway.py\nversion_a\n```',
        '```file:backend/app/routers/gateway.py\nversion_b\n```',
        '```file:backend/app/routers/gateway.py\nmerged_final\n```',
    ]
    artifact_dir = tmp_path / "cycle-0002"
    artifact_dir.mkdir()
    result = ParallelOrchestrator(None, cfg, client).run(
        gap=_gap(),
        cycle_id=2,
        design_brief="# brief",
        shared_context="ctx",
        artifact_dir=artifact_dir,
    )
    assert result.synthesizer_used is True
    assert "merged_final" in result.merged_blocks["backend/app/routers/gateway.py"]
    assert client.chat.call_count == 3
