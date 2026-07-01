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


def test_parallel_orchestrator_merges_non_conflicting_workers(mock_target_repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    cfg = ParallelConfig(
        enabled=True,
        max_workers=2,
        synthesizer_enabled=True,
        run_review_stage=False,
        workers=[
            WorkerSpec("backend_tests", "Tests", "tests", [], stage="implement"),
            WorkerSpec("governance_docs", "Docs", "docs", [], stage="implement"),
        ],
    )
    client = MagicMock()
    client.chat.side_effect = [
        '```file:backend/tests/test_a.py\nassert True\n```',
        '```file:backend/tests/test_b.py\nassert True\n```',
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
    assert result.merged_blocks["backend/tests/test_a.py"].startswith("assert")
    assert result.merged_blocks["backend/tests/test_b.py"].startswith("assert")
    assert (artifact_dir / "subagents" / "backend_tests.md").exists()


def test_parallel_orchestrator_uses_synthesizer_on_conflict(mock_target_repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    cfg = ParallelConfig(
        enabled=True,
        max_workers=2,
        synthesizer_enabled=True,
        run_review_stage=False,
        workers=[
            WorkerSpec("backend_tests", "Tests", "tests", [], stage="implement"),
            WorkerSpec("governance_docs", "Docs", "docs", [], stage="implement"),
        ],
    )
    client = MagicMock()
    client.chat.side_effect = [
        '```file:backend/tests/test_x.py\nversion_a\n```',
        '```file:backend/tests/test_x.py\nversion_b\n```',
        '```file:backend/tests/test_x.py\nmerged_final\n```',
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
    assert "merged_final" in result.merged_blocks["backend/tests/test_x.py"]
    assert client.chat.call_count == 3
