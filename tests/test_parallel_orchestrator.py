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
            WorkerSpec("backend_contract", "Backend", "backend", [], stage="implement"),
            WorkerSpec("backend_tests", "Tests", "tests", [], stage="implement"),
        ],
    )
    client = MagicMock()
    client.chat.side_effect = [
        '```file:backend/app/routers/gateway_extra.py\n@router.get("/x")\n```',
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
    assert result.guardrail_result is not None and result.guardrail_result.passed
    assert result.merged_blocks
    assert (artifact_dir / "subagents" / "backend_contract.md").exists()


def test_parallel_orchestrator_uses_synthesizer_on_conflict(mock_target_repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
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
        '```file:backend/tests/test_x.py\nversion_a\n```',
        '```file:backend/tests/test_x.py\nversion_b\n```',
        '```file:backend/tests/test_x.py\nmerged_final\n```',
    ]
    artifact_dir = tmp_path / "cycle-0002"
    artifact_dir.mkdir()
    result = ParallelOrchestrator(None, cfg, client).run(
        gap=_gap(),
        cycle_id=1,
        design_brief="# brief",
        shared_context="ctx",
        artifact_dir=artifact_dir,
    )
    assert result.synthesizer_used is True
    assert any("merged_final" in content for content in result.merged_blocks.values())
    assert client.chat.call_count == 3


def test_parallel_orchestrator_skips_review_for_governance_only(mock_target_repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    cfg = ParallelConfig(
        enabled=True,
        max_workers=2,
        synthesizer_enabled=True,
        run_review_stage=True,
        workers=[
            WorkerSpec("governance_docs", "Governance", "governance", [], stage="implement"),
            WorkerSpec("audit_architect", "Audit", "audit", [], stage="review", write_mode="review"),
        ],
    )
    client = MagicMock()
    client.chat.return_value = (
        '```file:backend/docs/governance/api-inventory-and-ui-map.md\n| row | updated |\n```'
    )
    artifact_dir = tmp_path / "cycle-gov"
    artifact_dir.mkdir()
    result = ParallelOrchestrator(None, cfg, client).run(
        gap=_gap(),
        cycle_id=390,
        design_brief="# brief",
        shared_context="ctx",
        artifact_dir=artifact_dir,
    )
    assert result.review_subagents == []
    assert result.review_guardrail_result is None
    assert client.chat.call_count == 1
