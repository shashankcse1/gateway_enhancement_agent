"""Full SDLC pipeline orchestration."""

from __future__ import annotations

import os

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.capability_coverage import CapabilityCoverage
from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.competitor_web_research import maybe_refresh_competitor_research
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.gap_models import GapItem, gap_from_dict, gap_to_dict
from gateway_enhancement_agent.code_implementer import CodeImplementer
from gateway_enhancement_agent.git_automation import (
    GitAutomator,
    MergeResult,
    fully_autonomous,
    merge_report_json,
    merge_report_markdown,
)
from gateway_enhancement_agent.prompt_emitter import (
    build_agent_work_order,
    build_design_brief,
    build_doc_sync_checklist,
    build_implementation_report,
    build_release_draft,
)
from gateway_enhancement_agent.self_test_runner import SelfTestRunner
from gateway_enhancement_agent.sdlc_validate import (
    combined_report_markdown,
    combined_summary,
    run_combined_validation,
)
from gateway_enhancement_agent.mirror_sync import sync_mirror
from gateway_enhancement_agent.progress_log import log, log_cycle_banner, log_hint, log_phase_done, log_phase_start
from gateway_enhancement_agent.state_store import CycleState, StateStore
from gateway_enhancement_agent.target_inventory import TargetInventory
from gateway_enhancement_agent.test_repair import repair_test_file, structured_pytest_failure


class SDLCPipeline:
    def __init__(self, store: StateStore | None = None) -> None:
        self.store = store or StateStore()
        self.backlog = BacklogStore()

    def run_cycle(self, *, skip_validation: bool = False) -> CycleState:
        repo = TargetInventory().repo
        cycle = self.store.begin_cycle(str(repo))
        autonomous = fully_autonomous()
        log_cycle_banner(cycle.cycle_id)
        log_phase_start("cycle", f"#{cycle.cycle_id} target={repo}")
        if autonomous:
            skip_validation = False
            try:
                cycle.metadata["git_start_branch"] = GitAutomator().current_branch()
            except Exception:  # noqa: BLE001
                cycle.metadata["git_start_branch"] = "main"
            self.store.update_cycle(cycle)

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
                cycle.metadata["validation_passed"] = False
            if autonomous:
                cycle = self._phase_merge(cycle)
            cycle = self._phase_document(cycle)
            cycle = self._phase_release_prep(cycle)
            self._write_cycle_summary(cycle)
            if autonomous:
                impl_ok = cycle.metadata.get("local_implementation_succeeded")
                files = list(cycle.metadata.get("local_implementation_files") or [])
                merge_ok = cycle.metadata.get("merge_succeeded")
                if not files and not impl_ok:
                    if cycle.metadata.get("no_open_gaps"):
                        cycle.status = "completed"
                        cycle.metadata["validation_passed"] = True
                    else:
                        cycle.status = "failed"
                        if cycle.active_gap_id and not cycle.errors:
                            cycle.errors.append("Autonomous cycle produced no implementation for active gap")
                elif not cycle.metadata.get("validation_passed", False):
                    cycle.status = "failed"
                elif impl_ok and not merge_ok:
                    cycle.status = "failed"
                elif cycle.errors:
                    cycle.status = "failed"
                else:
                    cycle.status = "completed"
            elif not skip_validation and not cycle.metadata.get("validation_passed", True):
                cycle.status = "failed"
            else:
                cycle.status = "completed"
            cycle.phase = "done"
        except Exception as exc:  # noqa: BLE001 — surface pipeline errors in state
            cycle.status = "failed"
            cycle.errors.append(str(exc))
            log(f"✗ cycle failed: {exc}", phase="cycle")
        finally:
            self.store.update_cycle(cycle)
            log_phase_done("cycle", f"#{cycle.cycle_id} status={cycle.status}")
        return cycle

    def _phase_discover(self, cycle: CycleState) -> CycleState:
        cycle.phase = "discover"
        log_phase_start("discover", "competitor research + inventory")
        research = maybe_refresh_competitor_research()
        cycle.metadata["competitor_web_research"] = research
        self.store.write_json(cycle.cycle_id, "competitor_web_research.json", research)
        try:
            mirror = sync_mirror()
            cycle.metadata["mirror_sync"] = mirror
            log(f"mirror sync: {len(mirror.get('files_copied', []))} file(s)", phase="discover")
        except OSError as exc:
            log(f"mirror sync skipped: {exc}", phase="discover")
        inv = TargetInventory().snapshot()
        comp = CompetitorRegistry().snapshot()
        self.store.write_json(cycle.cycle_id, "inventory_snapshot.json", inv)
        self.store.write_json(cycle.cycle_id, "competitor_snapshot.json", comp)
        cycle.completed_phases.append("discover")
        self.store.update_cycle(cycle)
        refreshed = "refreshed" if research.get("refreshed") else "cached"
        log_phase_done("discover", f"web research {refreshed}")
        return cycle

    def _phase_analyze(self, cycle: CycleState) -> CycleState:
        cycle.phase = "analyze"
        log_phase_start("analyze", "gap matrix + backlog")
        analyzer = GapAnalyzer()
        inv = analyzer.inventory.parse_inventory_gaps()
        reconciled = analyzer.backlog.reconcile_with_inventory(inv, analyzer.repo, cycle_id=cycle.cycle_id)
        if reconciled:
            log(f"backlog reconciled: {', '.join(reconciled[:5])}", phase="analyze")
        covered = analyzer.close_covered_gaps_in_backlog(cycle.cycle_id)
        if covered:
            log(f"auto-closed {len(covered)} gap(s) already covered by tests: {', '.join(covered)}", phase="analyze")
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
            cycle.metadata["active_gap_snapshot"] = gap_to_dict(top)
            cycle.metadata["competitor_ids"] = top.competitor_ids
            self.backlog.mark_scheduled(top.gap_id, cycle.cycle_id)
        else:
            cycle.metadata["no_open_gaps"] = True
        cycle.completed_phases.append("analyze")
        self.store.update_cycle(cycle)
        if top:
            log_phase_done("analyze", f"top gap [{top.gap_id}] {top.title}")
        else:
            log_phase_done("analyze", "no open gaps")
        return cycle

    def _phase_design(self, cycle: CycleState) -> CycleState:
        cycle.phase = "design"
        log_phase_start("design")
        gap = self._active_gap(cycle)
        if gap:
            self.store.write_text(cycle.cycle_id, "design_brief.md", build_design_brief(gap, cycle.cycle_id))
        cycle.completed_phases.append("design")
        self.store.update_cycle(cycle)
        log_phase_done("design")
        return cycle

    def _phase_implement(self, cycle: CycleState) -> CycleState:
        cycle.phase = "implement"
        log_phase_start("implement", "Ollama workers (this is the slowest phase)")
        gap = self._active_gap(cycle)
        if gap:
            design_brief = (self.store.cycle_dir(cycle.cycle_id) / "design_brief.md").read_text(encoding="utf-8")
            self.store.write_text(
                cycle.cycle_id,
                "agent_work_order.md",
                build_agent_work_order(gap, cycle.cycle_id),
            )
            artifact_dir = self.store.cycle_dir(cycle.cycle_id)
            result = CodeImplementer().implement(
                gap,
                cycle_id=cycle.cycle_id,
                design_brief=design_brief,
                artifact_dir=artifact_dir,
            )
            report = build_implementation_report(gap, cycle.cycle_id, result)
            self.store.write_text(cycle.cycle_id, "implementation_report.md", report)
            self.store.write_json(
                cycle.cycle_id,
                "implementation_report.json",
                {
                    "attempted": result.attempted,
                    "succeeded": result.succeeded,
                    "model": result.model,
                    "files_written": result.files_written,
                    "skipped_reason": result.skipped_reason,
                    "error": result.error,
                    "llm_response_path": result.llm_response_path,
                    "implementation_mode": result.implementation_mode,
                    "subagents_run": result.subagents_run,
                    "subagents_succeeded": result.subagents_succeeded,
                    "synthesizer_used": result.synthesizer_used,
                },
            )
            cycle.metadata["local_implementation_attempted"] = result.attempted
            cycle.metadata["local_implementation_succeeded"] = result.succeeded
            cycle.metadata["local_implementation_files"] = result.files_written
            cycle.metadata["implementation_mode"] = result.implementation_mode
            cycle.metadata["subagents_run"] = result.subagents_run
            if result.skipped_reason:
                cycle.metadata["local_implementation_skipped"] = result.skipped_reason
            if result.error:
                cycle.errors.append(f"Local implementation: {result.error}")
            if result.succeeded:
                log_phase_done("implement", f"wrote {len(result.files_written)} file(s)")
            elif result.skipped_reason:
                log_phase_done("implement", f"skipped: {result.skipped_reason}")
            else:
                log_phase_done("implement", f"failed: {result.error or 'unknown'}")
        else:
            log_phase_done("implement", "no active gap")
        cycle.completed_phases.append("implement")
        self.store.update_cycle(cycle)
        return cycle

    def _phase_validate(self, cycle: CycleState) -> CycleState:
        cycle.phase = "validate"
        changed = list(cycle.metadata.get("local_implementation_files") or [])
        if not changed:
            log_phase_start("validate", "self-tests only (no files changed)")
            return self._phase_validate_self_only(cycle)
        log_phase_start("validate", f"{len(changed)} changed file(s)")
        combined = run_combined_validation(changed_files=changed)
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
        gap = self._active_gap(cycle)
        if not summary["passed"] and changed and gap and not summary["target_validation_passed"]:
            failure_text = self._collect_target_failure_text(combined)
            log_phase_start("validate", "pytest repair loop")
            os.environ["AGENT_ALLOW_TEST_OVERWRITE"] = "1"
            repaired, repair_err = repair_test_file(gap, changed[0], failure_text)
            cycle.metadata["pytest_repair_attempted"] = True
            cycle.metadata["pytest_repair_succeeded"] = repaired
            if repaired:
                combined = run_combined_validation(changed_files=changed)
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
            else:
                cycle.metadata["pytest_repair_error"] = repair_err[:500]
        if not summary["passed"]:
            if not summary["self_test_passed"]:
                cycle.errors.append("Agent self-tests failed")
            if not summary["target_validation_passed"]:
                cycle.errors.append("Target repo validation gates failed")
            if gap:
                fail_reason = "; ".join(cycle.errors[-2:]) if cycle.errors else "validation failed"
                failures = self.backlog.record_validation_failure(gap.gap_id, cycle.cycle_id, reason=fail_reason)
                cycle.metadata["validation_failure_count"] = failures
                if self.backlog.should_auto_defer(gap.gap_id):
                    self.backlog.mark_deferred(
                        gap.gap_id,
                        cycle.cycle_id,
                        reason=f"pytest failed {failures}x — auto-deferred",
                    )
                    log(f"gap {gap.gap_id} deferred after {failures} validation failure(s)", phase="analyze")
        cycle.completed_phases.append("validate")
        self.store.update_cycle(cycle)
        log_phase_done("validate", "PASS" if summary["passed"] else "FAIL")
        return cycle

    def _phase_validate_self_only(self, cycle: CycleState) -> CycleState:
        cycle.phase = "validate"
        if cycle.metadata.get("no_open_gaps"):
            log_phase_start("validate", "skipped — no open gaps")
            cycle.metadata["validation_passed"] = True
            cycle.metadata["self_test_passed"] = True
            cycle.metadata["target_validation_skipped"] = True
            cycle.completed_phases.append("validate")
            self.store.update_cycle(cycle)
            log_phase_done("validate", "SKIP")
            return cycle
        log_phase_start("validate", "agent self-tests only")
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
        log_phase_done("validate", "PASS" if summary["passed"] else "FAIL")
        return cycle

    def _phase_merge(self, cycle: CycleState) -> CycleState:
        cycle.phase = "merge"
        log_phase_start("merge")
        gap = self._active_gap(cycle)
        files = list(cycle.metadata.get("local_implementation_files") or [])
        start_branch = cycle.metadata.get("git_start_branch", "main")
        automator = GitAutomator()

        if not gap or not files:
            cycle.metadata["merge_skipped"] = "no gap or no files written"
            cycle.metadata["merge_succeeded"] = not bool(files)
            cycle.completed_phases.append("merge")
            self.store.update_cycle(cycle)
            log_phase_done("merge", cycle.metadata["merge_skipped"])
            return cycle

        if not cycle.metadata.get("validation_passed", False):
            if automator.config.rollback_on_validation_failure:
                automator.rollback(files, start_branch)
                cycle.metadata["merge_rollback"] = True
            cycle.metadata["merge_succeeded"] = False
            cycle.metadata["merge_skipped"] = "validation failed"
            cycle.errors.append("Autonomous merge blocked: validation failed")
            if gap:
                self.store.write_text(
                    cycle.cycle_id,
                    "merge_report.md",
                    merge_report_markdown(
                        MergeResult(attempted=False, succeeded=False, skipped_reason="validation failed"),
                        gap,
                        cycle.cycle_id,
                    ),
                )
            cycle.completed_phases.append("merge")
            self.store.update_cycle(cycle)
            log_phase_done("merge", "validation failed")
            return cycle

        result = automator.commit_and_merge(
            gap=gap,
            cycle_id=cycle.cycle_id,
            files_written=files,
            start_branch=start_branch,
        )
        cycle.metadata["merge_succeeded"] = result.succeeded
        cycle.metadata["merge_commit_sha"] = result.commit_sha
        cycle.metadata["merge_branch"] = result.merge_branch
        cycle.metadata["merge_pushed"] = result.pushed
        if result.skipped_reason:
            cycle.metadata["merge_skipped"] = result.skipped_reason
        if result.error:
            cycle.errors.append(f"Autonomous merge: {result.error}")
        if result.succeeded and gap:
            self.backlog.mark_closed(gap.gap_id, cycle.cycle_id, commit_sha=result.commit_sha)
        self.store.write_text(cycle.cycle_id, "merge_report.md", merge_report_markdown(result, gap, cycle.cycle_id))
        self.store.write_json(cycle.cycle_id, "merge_report.json", merge_report_json(result))
        cycle.completed_phases.append("merge")
        self.store.update_cycle(cycle)
        if result.succeeded:
            log_phase_done("merge", f"commit {result.commit_sha or '—'} pushed={result.pushed}")
        else:
            log_phase_done("merge", result.skipped_reason or result.error or "skipped")
        return cycle

    def _phase_document(self, cycle: CycleState) -> CycleState:
        cycle.phase = "document"
        log_phase_start("document")
        gap = self._active_gap(cycle)
        if gap:
            self.store.write_text(
                cycle.cycle_id,
                "doc_sync_checklist.md",
                build_doc_sync_checklist(gap),
            )
        cycle.completed_phases.append("document")
        self.store.update_cycle(cycle)
        log_phase_done("document")
        return cycle

    def _phase_release_prep(self, cycle: CycleState) -> CycleState:
        cycle.phase = "release_prep"
        log_phase_start("release_prep")
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
        log_phase_done("release_prep")
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

    def _active_gap(self, cycle: CycleState) -> GapItem | None:
        snapshot = cycle.metadata.get("active_gap_snapshot")
        if snapshot:
            return gap_from_dict(snapshot)
        analyzer = GapAnalyzer()
        if cycle.active_gap_id:
            for gap in analyzer.build_matrix():
                if gap.gap_id == cycle.active_gap_id:
                    return gap
            return self._gap_from_inventory(cycle.active_gap_id)
        return analyzer.top_gap()

    def _gap_from_inventory(self, gap_id: str) -> GapItem | None:
        """Resolve a gap by id even when it left the live matrix (e.g. after tests were written)."""
        if not gap_id.startswith("inv-"):
            return None
        try:
            idx = int(gap_id.split("-", 1)[1])
        except ValueError:
            return None
        inv = GapAnalyzer().inventory.parse_inventory_gaps()
        if idx < 0 or idx >= len(inv):
            return None
        gap = inv[idx]
        route = f"{gap.method} {gap.route}".strip()
        return GapItem(
            gap_id=gap_id,
            title=route,
            source="api_inventory",
            priority=2,
            score=10,
            route=route,
            coverage=gap.coverage,
            rationale=gap.notes or "",
        )

    @staticmethod
    def _collect_target_failure_text(combined) -> str:
        parts: list[str] = []
        for result in combined.target_results:
            if result.passed:
                continue
            if result.gate_id == "gateway_pytest":
                parts.append(structured_pytest_failure(result.stdout_tail, result.stderr_tail))
            elif result.stderr_tail or result.stdout_tail:
                parts.append((result.stderr_tail or result.stdout_tail).strip())
        return "\n".join(parts)[:3000]
