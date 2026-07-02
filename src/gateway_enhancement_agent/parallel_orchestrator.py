"""Parallel subagent orchestration — independent workers + synthesizer merge."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from gateway_enhancement_agent.config import load_json, target_repo
from gateway_enhancement_agent.delivery_config import (
    DeliveryConfig,
    filter_blocks_for_delivery,
    should_skip_review_stage,
    suggest_test_path,
)
from gateway_enhancement_agent.gap_intelligence import (
    build_tests_first_user_prompt,
    normalize_test_blocks,
    parse_route,
    pick_test_template,
)
from gateway_enhancement_agent.repo_access import read_repo_file
from gateway_enhancement_agent.edit_instructions import (
    GOVERNANCE_PATCH_BLOCK_INSTRUCTION,
    IMPLEMENT_FILE_BLOCK_INSTRUCTION,
    PATCH_BLOCK_INSTRUCTION,
    UI_PATCH_BLOCK_INSTRUCTION,
)
from gateway_enhancement_agent.file_blocks import (
    drop_unchanged_blocks,
    extract_file_blocks,
    merge_response_previews,
    preview_llm_edits,
    write_content_blocks,
)
from gateway_enhancement_agent.gap_analyzer import GapItem
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient
from gateway_enhancement_agent.patch_blocks import (
    exact_anchor_lines,
    extract_search_replace_hunks,
    governance_row_snippet,
    scoped_file_snippet,
    ui_scoped_snippet,
)
from gateway_enhancement_agent.progress_log import log
from gateway_enhancement_agent.prompt_budget import build_context_from_paths
from gateway_enhancement_agent.route_modules import (
    handler_anchors_for_gap,
    path_hints_for_gap,
    ui_anchors_for_gap,
    ui_append_hint_for_gap,
)
from gateway_enhancement_agent.security_guardrails import GuardrailResult, SecurityGuardrails


@dataclass
class WorkerSpec:
    worker_id: str
    label: str
    focus: str
    path_hints: list[str]
    stage: str = "implement"
    component: str | None = None
    role_lens: str | None = None
    write_mode: str = "patch"


@dataclass
class ParallelConfig:
    enabled: bool
    max_workers: int
    synthesizer_enabled: bool
    run_review_stage: bool
    workers: list[WorkerSpec]

    @classmethod
    def from_env(cls) -> ParallelConfig:
        raw = load_json("parallel_workers.json")
        delivery = DeliveryConfig.from_env()
        env_on = os.environ.get("PARALLEL_IMPLEMENT", "").strip().lower()
        enabled = bool(raw.get("enabled", True))
        if env_on in {"0", "false", "no"}:
            enabled = False
        elif env_on in {"1", "true", "yes"}:
            enabled = True
        workers = [
            WorkerSpec(
                worker_id=w["id"],
                label=w["label"],
                focus=w["focus"],
                path_hints=list(w.get("path_hints", [])),
                stage=w.get("stage", "implement"),
                component=w.get("component"),
                role_lens=w.get("role_lens"),
                write_mode=w.get("write_mode", "patch"),
            )
            for w in raw.get("workers", [])
        ]
        preferred = delivery.prefer_implement_workers
        if preferred:
            order = {wid: idx for idx, wid in enumerate(preferred)}
            workers.sort(key=lambda w: (0 if w.stage == "implement" else 1, order.get(w.worker_id, 99), w.worker_id))
        return cls(
            enabled=enabled,
            max_workers=int(os.environ.get("PARALLEL_MAX_WORKERS", delivery.max_parallel_workers)),
            synthesizer_enabled=bool(raw.get("synthesizer_enabled", True)),
            run_review_stage=bool(raw.get("run_review_stage", True)),
            workers=workers,
        )


@dataclass
class SubagentResult:
    worker_id: str
    label: str
    succeeded: bool
    stage: str = "implement"
    component: str | None = None
    role_lens: str | None = None
    write_mode: str = "patch"
    response: str = ""
    file_blocks: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ParallelImplementResult:
    mode: str
    subagents: list[SubagentResult] = field(default_factory=list)
    review_subagents: list[SubagentResult] = field(default_factory=list)
    merged_response: str = ""
    merged_blocks: dict[str, str] = field(default_factory=dict)
    synthesizer_used: bool = False
    guardrail_result: GuardrailResult | None = None
    review_guardrail_result: GuardrailResult | None = None
    error: str | None = None


class ParallelOrchestrator:
    FILE_BLOCK_INSTRUCTION = IMPLEMENT_FILE_BLOCK_INSTRUCTION
    PATCH_INSTRUCTION = PATCH_BLOCK_INSTRUCTION
    REVIEW_INSTRUCTION = (
        "Respond with a structured review markdown. Include sections: Summary, Findings, "
        "Risk level (LOW/MEDIUM/HIGH), and a final line `Verdict: APPROVE` or `Verdict: BLOCKER`. "
        "Use BLOCKER only when the merged proposal is unsafe to apply as-is. "
        "Use APPROVE when authz, audit, tests, and operational controls in the proposal address the risks."
    )

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        parallel_config: ParallelConfig | None = None,
        client: LocalLLMClient | None = None,
    ) -> None:
        self.llm_config = llm_config or LLMConfig.from_env()
        self.parallel_config = parallel_config or ParallelConfig.from_env()
        self.client = client or LocalLLMClient(self.llm_config)
        self.guardrails = SecurityGuardrails()

    def run(
        self,
        *,
        gap: GapItem,
        cycle_id: int,
        design_brief: str,
        shared_context: str,
        artifact_dir: Path,
    ) -> ParallelImplementResult:
        repo = target_repo()
        implement_workers = [w for w in self.parallel_config.workers if w.stage == "implement" and w.write_mode == "patch"]
        delivery = DeliveryConfig.from_env()
        if delivery.tests_first or (delivery.full and delivery.prefer_implement_workers):
            preferred = set(
                delivery.implement_workers_for_gap(cycle_id, gap, repo)
                if delivery.full
                else delivery.implement_workers_for_cycle(cycle_id)
            ) or (
                {"backend_tests"} if delivery.tests_first else {"backend_contract", "backend_tests"}
            )
            implement_workers = [w for w in implement_workers if w.worker_id in preferred]
        if not implement_workers:
            return ParallelImplementResult(mode="parallel", error="No implement workers configured")

        log(
            f"parallel implement: {len(implement_workers)} worker(s), max_workers={self.parallel_config.max_workers}",
            phase="implement",
        )
        subagent_dir = artifact_dir / "subagents"
        subagent_dir.mkdir(parents=True, exist_ok=True)
        implement_results = self._run_workers_parallel(
            implement_workers,
            gap=gap,
            cycle_id=cycle_id,
            design_brief=design_brief,
            shared_context=shared_context,
            merged_proposal=None,
            subagent_dir=subagent_dir,
        )

        merged = self._merge_results(gap, cycle_id, design_brief, implement_results, artifact_dir)
        filtered_blocks, dropped = filter_blocks_for_delivery(merged.merged_blocks, repo)
        filtered_blocks = normalize_test_blocks(filtered_blocks, gap_id=gap.gap_id, route=gap.route)
        filtered_blocks, noop_dropped = drop_unchanged_blocks(repo, filtered_blocks)
        dropped = list(dropped) + noop_dropped
        if not filtered_blocks and noop_dropped:
            merged.error = "No effective changes after merge (all blocks were no-ops)"
        if dropped:
            log(f"dropped forbidden/no-op paths: {', '.join(dropped)}", phase="implement")
        merged.merged_blocks = filtered_blocks
        if filtered_blocks:
            merged.merged_response = self._blocks_to_response(filtered_blocks)
        merged.guardrail_result = self.guardrails.check_blocks(merged.merged_blocks, repo_root=repo)

        review_results: list[SubagentResult] = []
        skip_review = should_skip_review_stage(list(merged.merged_blocks.keys()))
        if skip_review:
            log("skipping review stage — governance/test-only changes", phase="implement")
        if self.parallel_config.run_review_stage and merged.merged_blocks and not skip_review:
            review_workers = [w for w in self.parallel_config.workers if w.stage == "review"]
            log(f"parallel review: {len(review_workers)} worker(s)", phase="implement")
            review_results = self._run_workers_parallel(
                review_workers,
                gap=gap,
                cycle_id=cycle_id,
                design_brief=design_brief,
                shared_context=shared_context,
                merged_proposal=merged.merged_response,
                subagent_dir=subagent_dir,
            )
            reviews = {r.worker_id: r.response for r in review_results if r.response}
            merged.review_subagents = review_results
            merged.review_guardrail_result = self.guardrails.check_reviews(reviews)
            (artifact_dir / "role_lens_reviews.md").write_text(
                self._format_reviews(review_results),
                encoding="utf-8",
            )

        merged.subagents = implement_results
        self._write_summary(artifact_dir, merged, implement_results, review_results)
        (artifact_dir / "parallel_merge.md").write_text(merged.merged_response, encoding="utf-8")
        return merged

    def _run_workers_parallel(
        self,
        workers: list[WorkerSpec],
        *,
        gap: GapItem,
        cycle_id: int,
        design_brief: str,
        shared_context: str,
        merged_proposal: str | None,
        subagent_dir: Path,
    ) -> list[SubagentResult]:
        results: list[SubagentResult] = []
        if not workers:
            return results
        with ThreadPoolExecutor(max_workers=min(self.parallel_config.max_workers, len(workers))) as pool:
            futures = {
                pool.submit(
                    self._run_worker,
                    worker,
                    gap=gap,
                    cycle_id=cycle_id,
                    design_brief=design_brief,
                    shared_context=shared_context,
                    merged_proposal=merged_proposal,
                ): worker
                for worker in workers
            }
            for future in as_completed(futures):
                worker = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = SubagentResult(
                        worker_id=worker.worker_id,
                        label=worker.label,
                        succeeded=False,
                        stage=worker.stage,
                        component=worker.component,
                        role_lens=worker.role_lens,
                        write_mode=worker.write_mode,
                        error=str(exc),
                    )
                suffix = "_review" if worker.write_mode == "review" else ""
                out = subagent_dir / f"{result.worker_id}{suffix}.md"
                out.write_text(result.response or result.error or "", encoding="utf-8")
                meta_path = subagent_dir / f"{result.worker_id}.json"
                meta_path.write_text(
                    json.dumps(
                        {
                            "worker_id": result.worker_id,
                            "label": result.label,
                            "stage": result.stage,
                            "component": result.component,
                            "role_lens": result.role_lens,
                            "write_mode": result.write_mode,
                            "succeeded": result.succeeded,
                            "files": sorted(result.file_blocks.keys()),
                            "error": result.error,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                results.append(result)
                status = "ok" if result.succeeded else "fail"
                files = ", ".join(sorted(result.file_blocks.keys())) or "—"
                log(f"worker {result.worker_id} ({worker.stage}) {status}: {files}", phase="implement")
        results.sort(key=lambda r: r.worker_id)
        return results

    def _run_worker(
        self,
        worker: WorkerSpec,
        *,
        gap: GapItem,
        cycle_id: int,
        design_brief: str,
        shared_context: str,
        merged_proposal: str | None,
    ) -> SubagentResult:
        repo = target_repo()
        worker_context = self._worker_context(repo, worker, shared_context, gap)
        component_line = f"Component: `{worker.component}`." if worker.component else ""
        lens_line = f"Role lens: `{worker.role_lens}`." if worker.role_lens else ""

        if worker.write_mode == "review":
            system = (
                f"You are review subagent `{worker.worker_id}` ({worker.label}). {lens_line} {component_line} "
                f"{worker.focus} {self.REVIEW_INSTRUCTION}"
            )
            user = f"""# Role-lens review — cycle {cycle_id:04d} / `{worker.worker_id}`

## Gap
- ID: {gap.gap_id}
- Title: {gap.title}
- Route: {gap.route or 'N/A'}

## Merged proposal to review
{merged_proposal or '_No proposal_'}

## Design brief
{design_brief}

## Context
{worker_context}
"""
            response = self.client.chat(system=system, user=user, label=f"review:{worker.worker_id}")
            return SubagentResult(
                worker_id=worker.worker_id,
                label=worker.label,
                succeeded=bool(response.strip()),
                stage=worker.stage,
                component=worker.component,
                role_lens=worker.role_lens,
                write_mode=worker.write_mode,
                response=response,
            )

        use_patch = worker.write_mode == "patch" and worker.worker_id != "backend_tests"
        if worker.worker_id in {"frontend_ui", "governance_docs"}:
            instruction = (
                GOVERNANCE_PATCH_BLOCK_INSTRUCTION
                if worker.worker_id == "governance_docs"
                else UI_PATCH_BLOCK_INSTRUCTION
            )
        elif use_patch:
            instruction = self.PATCH_INSTRUCTION
        else:
            instruction = self.FILE_BLOCK_INSTRUCTION
        system = (
            f"You are implement subagent `{worker.worker_id}` ({worker.label}). {component_line} "
            f"Your scope: {worker.focus} Follow AGENTS.md. Implement ONLY your component slice. "
            + instruction
        )
        user = f"""# Subtask — cycle {cycle_id:04d} / worker `{worker.worker_id}`

## Gap
- ID: {gap.gap_id}
- Title: {gap.title}
- Route: {gap.route or 'N/A'}
- Coverage: {gap.coverage or 'N/A'}

## Your focus
{worker.focus}

## Design brief
{design_brief}

## Repository context
Target root: {repo}

{worker_context}

Produce file blocks ONLY for files in your component scope.
"""
        if worker.worker_id == "frontend_ui" and gap is not None:
            append_hint = ui_append_hint_for_gap(gap)
            if append_hint:
                user += f"\n## UI patch guidance\n{append_hint}\n"
            user += (
                "\n## Patch constraints\n"
                "- Use ONE SEARCH/REPLACE hunk per file (5-15 lines in SEARCH).\n"
                "- Copy SEARCH lines verbatim from the anchor snippets below — no truncated placeholders.\n"
            )
        delivery = DeliveryConfig.from_env()
        if worker.worker_id == "backend_tests":
            target_test = suggest_test_path(gap.gap_id, gap.route)
            template_rel = pick_test_template(gap.route or gap.title)
            user = build_tests_first_user_prompt(
                gap=gap,
                cycle_id=cycle_id,
                design_brief=design_brief,
                context=worker_context,
                target_test=target_test,
                template_rel=template_rel,
            )
        response = self.client.chat(system=system, user=user, label=f"implement:{worker.worker_id}")
        preview = preview_llm_edits(repo, response)
        blocks = preview if preview else extract_file_blocks(response)
        has_edits = bool(preview)
        if not has_edits and worker.write_mode == "patch":
            hunks = extract_search_replace_hunks(response)
            if hunks and not preview:
                has_edits = False
            elif not hunks:
                has_edits = bool(blocks)
        return SubagentResult(
            worker_id=worker.worker_id,
            label=worker.label,
            succeeded=has_edits,
            stage=worker.stage,
            component=worker.component,
            role_lens=worker.role_lens,
            write_mode=worker.write_mode,
            response=response,
            file_blocks=preview or blocks,
            error=None if has_edits else "No applicable SEARCH/REPLACE patches (SEARCH did not match repo)",
        )

    def _worker_context(self, repo: Path, worker: WorkerSpec, shared_context: str, gap: GapItem | None = None) -> str:
        delivery = DeliveryConfig.from_env()
        hints = list(worker.path_hints)
        if gap is not None:
            hints = path_hints_for_gap(gap, worker.worker_id) or hints
        if delivery.tests_first:
            max_files = min(2, len(hints))
            max_chars = self.llm_config.tests_first_max_file_chars
            budget = max(512, self.llm_config.effective_max_prompt_tokens() // 3)
            built = build_context_from_paths(
                [p for p in hints if p.startswith("backend/tests/")][:max_files] or hints[:max_files],
                read_file=read_repo_file,
                max_files=max_files,
                max_file_chars=max_chars,
                max_total_tokens=budget,
            )
            if built != "_No context files found._":
                return built
        chunks: list[str] = []
        per_file = min(self.llm_config.max_file_chars // 2, self.llm_config.tests_first_max_file_chars)
        anchors = handler_anchors_for_gap(gap) if gap else []
        ui_worker = gap is not None and worker.worker_id == "frontend_ui"
        gov_worker = gap is not None and worker.worker_id == "governance_docs"
        if ui_worker:
            anchors = ui_anchors_for_gap(gap)
            hints = [h for h in hints if h.startswith("frontend/")][:2]
        elif gov_worker:
            hints = [h for h in hints if h.startswith("backend/docs/governance/")]
            if gap.route:
                _method, path = parse_route(gap.route)
                anchors = [path.strip()]
            else:
                anchors = []
        hint_limit = 2 if ui_worker else (3 if gov_worker else self.llm_config.tests_first_max_context_files)
        ui_max_chars = min(per_file, 2200)
        for rel in hints[:hint_limit]:
            text = read_repo_file(rel)
            if not text:
                continue
            if gov_worker and gap and gap.route:
                _method, path = parse_route(gap.route)
                text = governance_row_snippet(text, path.strip())
            elif ui_worker:
                full_text = text
                text = ui_scoped_snippet(full_text, anchors=anchors, max_chars=ui_max_chars)
                exact = exact_anchor_lines(full_text, anchors=anchors)
                if exact:
                    text = f"Exact SEARCH anchor (copy verbatim):\n{exact}\n\n---\n{text}"
            elif delivery.full and delivery.requires_patch_mode(rel, repo) and anchors:
                text = scoped_file_snippet(text, anchors=anchors, max_chars=per_file)
            elif len(text) > per_file:
                text = text[:per_file] + "\n... [truncated]"
            chunks.append(f"### `{rel}`\n```\n{text}\n```")
        if chunks:
            return "\n\n".join(chunks)
        return shared_context

    def _merge_results(
        self,
        gap: GapItem,
        cycle_id: int,
        design_brief: str,
        results: list[SubagentResult],
        artifact_dir: Path,
    ) -> ParallelImplementResult:
        combined: dict[str, list[tuple[str, str]]] = {}
        for result in results:
            for rel, content in result.file_blocks.items():
                combined.setdefault(rel, []).append((result.worker_id, content))

        if not combined:
            return ParallelImplementResult(mode="parallel", subagents=results, error="No file blocks from any subagent")

        unique = {rel: versions[0][1] for rel, versions in combined.items() if len(versions) == 1}
        conflicts = {rel: versions for rel, versions in combined.items() if len(versions) > 1}

        if not conflicts or not self.parallel_config.synthesizer_enabled:
            merged_blocks = dict(unique)
            for rel, versions in conflicts.items():
                priority = ["backend_contract", "backend_tests", "frontend_ui", "governance_docs"]
                chosen = versions[0][1]
                for pid in priority:
                    for wid, content in versions:
                        if wid == pid:
                            chosen = content
                            break
                merged_blocks[rel] = chosen
            response = self._blocks_to_response(merged_blocks)
            return ParallelImplementResult(
                mode="parallel",
                subagents=results,
                merged_response=response,
                merged_blocks=merged_blocks,
                synthesizer_used=False,
            )

        conflict_report = self._format_conflicts(conflicts)
        (artifact_dir / "subagents" / "conflicts.md").write_text(conflict_report, encoding="utf-8")
        system = (
            "You are the synthesizer subagent. Merge component worker outputs into one coherent slice. "
            "Preserve security, audit, and least-privilege from AGENTS.md. "
            "Use SEARCH/REPLACE for existing large files; use ```file:``` only for new small files. "
            + self.PATCH_INSTRUCTION
        )
        user = f"""# Synthesizer merge — cycle {cycle_id:04d}

## Gap
{gap.title} (`{gap.gap_id}`)

## Design brief
{design_brief}

## Non-conflicting files
{self._blocks_to_response(unique)}

## Conflicting files
{conflict_report}

Output final merged file blocks for ALL files.
"""
        log("synthesizer merging conflicting worker outputs", phase="implement")
        merged_response = self.client.chat(system=system, user=user, label="synthesizer")
        merged_blocks = preview_llm_edits(target_repo(), merged_response) or extract_file_blocks(merged_response)
        if not merged_blocks:
            merged_blocks = {**unique, **{rel: v[0][1] for rel, v in conflicts.items()}}
            merged_response = self._blocks_to_response(merged_blocks)
            return ParallelImplementResult(
                mode="parallel",
                subagents=results,
                merged_response=merged_response,
                merged_blocks=merged_blocks,
                synthesizer_used=False,
                error="Synthesizer returned no blocks; used priority fallback",
            )
        return ParallelImplementResult(
            mode="parallel",
            subagents=results,
            merged_response=merged_response,
            merged_blocks=merged_blocks,
            synthesizer_used=True,
        )

    def _write_summary(
        self,
        artifact_dir: Path,
        merged: ParallelImplementResult,
        implement_results: list[SubagentResult],
        review_results: list[SubagentResult],
    ) -> None:
        (artifact_dir / "parallel_summary.json").write_text(
            json.dumps(
                {
                    "mode": "parallel",
                    "implement_workers": len(implement_results),
                    "review_workers": len(review_results),
                    "synthesizer_used": merged.synthesizer_used,
                    "files_merged": sorted(merged.merged_blocks.keys()),
                    "guardrail_passed": merged.guardrail_result.passed if merged.guardrail_result else None,
                    "guardrail_violations": merged.guardrail_result.violations if merged.guardrail_result else [],
                    "review_blockers": merged.review_guardrail_result.violations if merged.review_guardrail_result else [],
                    "subagents": [
                        {
                            "worker_id": r.worker_id,
                            "stage": r.stage,
                            "component": r.component,
                            "role_lens": r.role_lens,
                            "succeeded": r.succeeded,
                        }
                        for r in implement_results + review_results
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _format_reviews(results: list[SubagentResult]) -> str:
        parts = ["# Role-lens reviews", ""]
        for r in results:
            parts.append(f"## {r.label} (`{r.worker_id}`)")
            parts.append(r.response or r.error or "_empty_")
            parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _format_conflicts(conflicts: dict[str, list[tuple[str, str]]]) -> str:
        parts: list[str] = []
        for rel, versions in sorted(conflicts.items()):
            parts.append(f"### `{rel}`")
            for wid, content in versions:
                parts.append(f"#### Worker `{wid}`")
                parts.append(f"```\n{content[:4000]}\n```")
        return "\n\n".join(parts)

    @staticmethod
    def _blocks_to_response(blocks: dict[str, str]) -> str:
        parts: list[str] = []
        for rel, content in sorted(blocks.items()):
            parts.append(f"```file:{rel}\n{content.rstrip()}\n```")
        return "\n\n".join(parts) + "\n"
