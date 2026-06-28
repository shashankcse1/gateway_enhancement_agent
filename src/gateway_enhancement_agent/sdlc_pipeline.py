"""Full SDLC pipeline orchestration."""

from __future__ import annotations

import os

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.capability_coverage import CapabilityCoverage
from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.prompt_emitter import (
    build_agent_work_order,
    build_design_brief,
    build_doc_sync_checklist,
    build_release_draft,
)
from gateway_enhancement_agent.self_test_runner import SelfTestRunner
from gateway_enhancement_agent.sdlc_validate import (
    combined_report_markdown,
    combined_summary,
    run_combined_validation,
)
from gateway_enhancement_agent.state_store import CycleState, StateStore
from gateway_enhancement_agent.target_inventory import TargetInventory


class SDLCPipeline:
    def __init__(self, store: StateStore | None = None) -> None:
        self.store = store or StateStore()
        self.backlog = BacklogStore()

    def run_cycle(self, *, skip_validation: bool = False) -> CycleState:
        repo = TargetInventory().repo
        cycle = self.store.begin_cycle(str(repo))

        try:
            cycle = self._phase_discover(cycle)
            cycle = self._phase_analyze(cycle)
            cycle = self._phase_design(cycle)
            cycle = self._phase_implement(cycle)
            if not skip_validation:
                if os.environ.get("AGENT_SKIP_TARGET_VALIDATION", "").strip() in {"1", "true", "yes"}:
                    cycle = self._phase_validate_self_only(cycle)
                else:
                    cycle = self._phase_validate(cycle)
            else:
                cycle.completed_phases.append("validate")
                cycle.metadata["validation_skipped"] = True
                cycle.metadata["validation_passed"] = True
            cycle = self._phase_document(cycle)
            cycle = self._phase_release_prep(cycle)
            self._write_cycle_summary(cycle)
            if not skip_validation and not cycle.metadata.get("validation_passed", True):
                cycle.status = "failed"
            else:
                cycle.status = "completed"
            cycle.phase = "done"
        except Exception as exc:  # noqa: BLE001 — surface pipeline errors in state
            cycle.status = "failed"
            cycle.errors.append(str(exc))
        finally:
            self.store.update_cycle(cycle)
        return cycle

    def _phase_discover(self, cycle: CycleState) -> CycleState:
        cycle.phase = "discover"
        inv = TargetInventory().snapshot()
        comp = CompetitorRegistry().snapshot()
        self.store.write_json(cycle.cycle_id, "inventory_snapshot.json", inv)
        self.store.write_json(cycle.cycle_id, "competitor_snapshot.json", comp)
        cycle.completed_phases.append("discover")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_analyze(self, cycle: CycleState) -> CycleState:
        cycle.phase = "analyze"
        analyzer = GapAnalyzer()
        matrix = analyzer.build_matrix()
        self.backlog.sync_from_matrix(matrix, cycle.cycle_id)
        self.store.write_json(cycle.cycle_id, "gap_matrix.json", analyzer.to_json())
        self.store.write_text(cycle.cycle_id, "gap_report.md", analyzer.report_markdown())
        coverage = CapabilityCoverage()
        self.store.write_json(cycle.cycle_id, "capability_coverage.json", coverage.to_json())
        self.store.write_text(cycle.cycle_id, "capability_coverage.md", coverage.report_markdown())
        self.store.write_text(cycle.cycle_id, "backlog.md", self.backlog.report_markdown())
        top = analyzer.top_gap()
        if top:
            cycle.active_gap_id = top.gap_id
            cycle.metadata["active_gap_title"] = top.title
            cycle.metadata["active_gap_score"] = top.score
            cycle.metadata["competitor_ids"] = top.competitor_ids
            self.backlog.mark_scheduled(top.gap_id, cycle.cycle_id)
        cycle.completed_phases.append("analyze")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_design(self, cycle: CycleState) -> CycleState:
        cycle.phase = "design"
        gap = self._active_gap(cycle)
        if gap:
            self.store.write_text(cycle.cycle_id, "design_brief.md", build_design_brief(gap, cycle.cycle_id))
        cycle.completed_phases.append("design")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_implement(self, cycle: CycleState) -> CycleState:
        cycle.phase = "implement"
        gap = self._active_gap(cycle)
        if gap:
            self.store.write_text(
                cycle.cycle_id,
                "agent_work_order.md",
                build_agent_work_order(gap, cycle.cycle_id),
            )
        cycle.completed_phases.append("implement")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_validate(self, cycle: CycleState) -> CycleState:
        cycle.phase = "validate"
        combined = run_combined_validation()
        summary = combined_summary(combined)
        self.store.write_json(cycle.cycle_id, "validation_report.json", summary)
        self.store.write_text(
            cycle.cycle_id,
            "validation_report.md",
            combined_report_markdown(combined),
        )
        cycle.metadata["validation_passed"] = summary["passed"]
        cycle.metadata["self_test_passed"] = summary["self_test_passed"]
        cycle.metadata["target_validation_passed"] = summary["target_validation_passed"]
        if not summary["passed"]:
            if not summary["self_test_passed"]:
                cycle.errors.append("Agent self-tests failed")
            if not summary["target_validation_passed"]:
                cycle.errors.append("Target repo validation gates failed")
        cycle.completed_phases.append("validate")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_validate_self_only(self, cycle: CycleState) -> CycleState:
        cycle.phase = "validate"
        runner = SelfTestRunner()
        results = runner.run_all()
        summary = {
            "passed": all(r.passed for r in results if r.required),
            "self_test_passed": all(r.passed for r in results if r.required),
            "target_validation_passed": None,
            "target_validation_skipped": True,
            "results": [{"gate_id": r.gate_id, "passed": r.passed} for r in results],
        }
        self.store.write_json(cycle.cycle_id, "validation_report.json", summary)
        cycle.metadata["validation_passed"] = summary["passed"]
        cycle.metadata["self_test_passed"] = summary["self_test_passed"]
        cycle.metadata["target_validation_skipped"] = True
        if not summary["passed"]:
            cycle.errors.append("Agent self-tests failed")
        cycle.completed_phases.append("validate")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_document(self, cycle: CycleState) -> CycleState:
        cycle.phase = "document"
        gap = self._active_gap(cycle)
        if gap:
            self.store.write_text(
                cycle.cycle_id,
                "doc_sync_checklist.md",
                build_doc_sync_checklist(gap),
            )
        cycle.completed_phases.append("document")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_release_prep(self, cycle: CycleState) -> CycleState:
        cycle.phase = "release_prep"
        gap = self._active_gap(cycle)
        passed = bool(cycle.metadata.get("validation_passed", False))
        skipped = bool(cycle.metadata.get("validation_skipped"))
        if gap:
            self.store.write_text(
                cycle.cycle_id,
                "release_decision_draft.md",
                build_release_draft(gap, cycle.cycle_id, passed if not skipped else True),
            )
        cycle.completed_phases.append("release_prep")
        self.store.update_cycle(cycle)
        return cycle

    def _write_cycle_summary(self, cycle: CycleState) -> None:
        self.store.write_json(
            cycle.cycle_id,
            "cycle_summary.json",
            {
                "cycle_id": cycle.cycle_id,
                "status": cycle.status,
                "active_gap_id": cycle.active_gap_id,
                "metadata": cycle.metadata,
                "completed_phases": cycle.completed_phases,
                "errors": cycle.errors,
            },
        )

    def _active_gap(self, cycle: CycleState):
        analyzer = GapAnalyzer()
        if cycle.active_gap_id:
            for gap in analyzer.build_matrix():
                if gap.gap_id == cycle.active_gap_id:
                    return gap
        return analyzer.top_gap()
