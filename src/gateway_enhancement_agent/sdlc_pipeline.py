"""Full SDLC pipeline orchestration."""

from __future__ import annotations

from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.prompt_emitter import (
    build_agent_work_order,
    build_design_brief,
    build_doc_sync_checklist,
    build_release_draft,
)
from gateway_enhancement_agent.state_store import CycleState, StateStore
from gateway_enhancement_agent.target_inventory import TargetInventory
from gateway_enhancement_agent.validation_runner import ValidationRunner


class SDLCPipeline:
    def __init__(self, store: StateStore | None = None) -> None:
        self.store = store or StateStore()

    def run_cycle(self, *, skip_validation: bool = False) -> CycleState:
        repo = TargetInventory().repo
        cycle = self.store.begin_cycle(str(repo))

        try:
            cycle = self._phase_discover(cycle)
            cycle = self._phase_analyze(cycle)
            cycle = self._phase_design(cycle)
            cycle = self._phase_implement(cycle)
            if not skip_validation:
                cycle = self._phase_validate(cycle)
            else:
                cycle.completed_phases.append("validate")
                cycle.metadata["validation_skipped"] = True
            cycle = self._phase_document(cycle)
            cycle = self._phase_release_prep(cycle)
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
        matrix = analyzer.to_json()
        self.store.write_json(cycle.cycle_id, "gap_matrix.json", matrix)
        self.store.write_text(cycle.cycle_id, "gap_report.md", analyzer.report_markdown())
        top = analyzer.top_gap()
        if top:
            cycle.active_gap_id = top.gap_id
            cycle.metadata["active_gap_title"] = top.title
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
        runner = ValidationRunner()
        results = runner.run_all()
        self.store.write_json(
            cycle.cycle_id,
            "validation_report.json",
            runner.summary(results),
        )
        self.store.write_text(
            cycle.cycle_id,
            "validation_report.md",
            runner.report_markdown(results),
        )
        cycle.metadata["validation_passed"] = runner.summary(results)["passed"]
        if not cycle.metadata["validation_passed"]:
            cycle.errors.append("One or more required validation gates failed")
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
        if gap:
            self.store.write_text(
                cycle.cycle_id,
                "release_decision_draft.md",
                build_release_draft(gap, cycle.cycle_id, passed),
            )
        cycle.completed_phases.append("release_prep")
        self.store.update_cycle(cycle)
        return cycle

    def _active_gap(self, cycle: CycleState):
        analyzer = GapAnalyzer()
        if cycle.active_gap_id:
            for gap in analyzer.build_matrix():
                if gap.gap_id == cycle.active_gap_id:
                    return gap
        return analyzer.top_gap()
