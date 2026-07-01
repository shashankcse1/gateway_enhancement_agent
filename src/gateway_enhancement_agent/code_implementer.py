"""Apply gateway gap fixes using a local LLM (Ollama CPU/GPU)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.file_blocks import apply_file_blocks, extract_file_blocks
from gateway_enhancement_agent.delivery_config import DeliveryConfig, filter_blocks_for_delivery, suggest_test_path
from gateway_enhancement_agent.gap_analyzer import GapItem
from gateway_enhancement_agent.gap_intelligence import (
    build_tests_first_user_prompt,
    is_auth_only_gap,
    normalize_test_blocks,
    pick_test_template,
    scaffold_auth_test,
)
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient
from gateway_enhancement_agent.parallel_orchestrator import ParallelConfig, ParallelOrchestrator
from gateway_enhancement_agent.prompt_budget import trim_to_token_budget
from gateway_enhancement_agent.repo_access import read_repo_file
from gateway_enhancement_agent.progress_log import log
from gateway_enhancement_agent.security_guardrails import SecurityGuardrails


@dataclass
class ImplementResult:
    attempted: bool
    succeeded: bool
    model: str | None = None
    files_written: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    error: str | None = None
    llm_response_path: str | None = None
    implementation_mode: str = "single"
    subagents_run: int = 0
    subagents_succeeded: int = 0
    synthesizer_used: bool = False


class CodeImplementer:
    FILE_BLOCK_INSTRUCTION = (
        "Respond ONLY with one or more file blocks in this exact format:\n"
        "```file:backend/path/to/file.py\n"
        "<full file contents>\n"
        "```\n"
        "Use paths relative to the repository root. Place tests under `backend/tests/` never `backend/app/tests/`. "
        "When editing large existing files, output the COMPLETE file — never truncate. "
        "Do not include secrets or .env files."
    )

    def __init__(self, config: LLMConfig | None = None, client: LocalLLMClient | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.client = client or LocalLLMClient(self.config)
        self.parallel_config = ParallelConfig.from_env()

    def _allowed_prefixes(self) -> list[str]:
        delivery = DeliveryConfig.from_env()
        if delivery.allowed_write_prefixes:
            return delivery.allowed_write_prefixes
        return self.config.allowed_path_prefixes

    def implement(
        self,
        gap: GapItem,
        *,
        cycle_id: int,
        design_brief: str,
        artifact_dir: Path,
    ) -> ImplementResult:
        if not self.config.auto_implement:
            return ImplementResult(
                attempted=False,
                succeeded=False,
                skipped_reason="LOCAL_LLM_AUTO_IMPLEMENT disabled",
            )
        health = self.client.health()
        if not health.reachable:
            return ImplementResult(
                attempted=False,
                succeeded=False,
                skipped_reason=health.error or "Local LLM unreachable",
            )
        if not health.model_available:
            return ImplementResult(
                attempted=False,
                succeeded=False,
                skipped_reason=f"Model not installed. Run: ollama pull {self.config.model}",
            )

        scaffold_result = self._try_scaffold_first(gap, cycle_id=cycle_id, artifact_dir=artifact_dir, model=health.model)
        if scaffold_result is not None:
            return scaffold_result

        if self.parallel_config.enabled:
            parallel_result = self._implement_parallel(
                gap, cycle_id=cycle_id, design_brief=design_brief, artifact_dir=artifact_dir, model=health.model
            )
            if (
                not parallel_result.succeeded
                and parallel_result.attempted
                and (
                    not parallel_result.files_written
                    or (parallel_result.error or "").startswith("No file blocks")
                    or "No file blocks" in (parallel_result.skipped_reason or "")
                )
            ):
                single_result = self._implement_single(
                    gap, cycle_id=cycle_id, design_brief=design_brief, artifact_dir=artifact_dir, model=health.model
                )
                if single_result.succeeded:
                    single_result.implementation_mode = "single_fallback"
                    return single_result
            return parallel_result
        return self._implement_single(gap, cycle_id=cycle_id, design_brief=design_brief, artifact_dir=artifact_dir, model=health.model)

    def _try_scaffold_first(
        self,
        gap: GapItem,
        *,
        cycle_id: int,
        artifact_dir: Path,
        model: str,
    ) -> ImplementResult | None:
        delivery = DeliveryConfig.from_env()
        if not delivery.tests_first or os.environ.get("AGENT_SCAFFOLD_EASY_GAPS", "1") != "1":
            return None
        if not is_auth_only_gap(gap):
            return None
        repo = target_repo()
        target = suggest_test_path(gap.gap_id, gap.route)
        if (repo / target).is_file():
            return None
        blocks = {target: scaffold_auth_test(gap, target)}
        guard = SecurityGuardrails().check_blocks(blocks, repo_root=repo)
        if not guard.passed:
            return None
        files_written = apply_file_blocks(
            repo,
            f"```file:{target}\n{blocks[target].rstrip()}\n```",
            allowed_prefixes=self._allowed_prefixes(),
        )
        if not files_written:
            return None
        log(f"scaffold-first: wrote {target}", phase="implement")
        (artifact_dir / "local_llm_response.md").write_text(
            f"# Scaffold-first (no LLM)\n\n```file:{target}\n{blocks[target]}\n```\n",
            encoding="utf-8",
        )
        return ImplementResult(
            attempted=True,
            succeeded=True,
            model=model,
            files_written=files_written,
            llm_response_path="local_llm_response.md",
            implementation_mode="scaffold_first",
        )

    def _implement_parallel(
        self,
        gap: GapItem,
        *,
        cycle_id: int,
        design_brief: str,
        artifact_dir: Path,
        model: str,
    ) -> ImplementResult:
        repo = target_repo()
        context = self._build_context(repo, gap)
        try:
            parallel = ParallelOrchestrator(self.config, self.parallel_config, self.client).run(
                gap=gap,
                cycle_id=cycle_id,
                design_brief=design_brief,
                shared_context=context,
                artifact_dir=artifact_dir,
            )
            if parallel.guardrail_result and not parallel.guardrail_result.passed:
                return ImplementResult(
                    attempted=True,
                    succeeded=False,
                    model=model,
                    implementation_mode="parallel",
                    error="Security guardrails blocked apply: " + "; ".join(parallel.guardrail_result.violations),
                )
            if parallel.review_guardrail_result and not parallel.review_guardrail_result.passed:
                return ImplementResult(
                    attempted=True,
                    succeeded=False,
                    model=model,
                    implementation_mode="parallel",
                    error="Role-lens BLOCKER: " + "; ".join(parallel.review_guardrail_result.violations),
                )
            llm_path = artifact_dir / "local_llm_response.md"
            blocks, dropped = filter_blocks_for_delivery(parallel.merged_blocks, repo)
            blocks = normalize_test_blocks(blocks, gap_id=gap.gap_id, route=gap.route)
            parallel.merged_blocks = blocks
            if dropped:
                log(f"filtered forbidden paths: {', '.join(dropped)}", phase="implement")
            if blocks:
                parallel.merged_response = ParallelOrchestrator._blocks_to_response(blocks)
            llm_path.write_text(parallel.merged_response, encoding="utf-8")
            if not blocks:
                return ImplementResult(
                    attempted=True,
                    succeeded=False,
                    model=model,
                    implementation_mode="parallel",
                    error=parallel.error or "No deliverable file blocks after filtering forbidden overwrites",
                    skipped_reason="All proposed files were forbidden overwrites or empty",
                )
            pre_apply = SecurityGuardrails().check_blocks(blocks, repo_root=repo)
            if not pre_apply.passed:
                return ImplementResult(
                    attempted=True,
                    succeeded=False,
                    model=model,
                    implementation_mode="parallel",
                    error="Pre-apply guardrails: " + "; ".join(pre_apply.violations),
                )
            files_written = apply_file_blocks(
                repo,
                "\n\n".join(f"```file:{p}\n{c.rstrip()}\n```" for p, c in sorted(blocks.items())),
                allowed_prefixes=self._allowed_prefixes(),
            )
            if files_written:
                log(f"applied files: {', '.join(files_written)}", phase="implement")
            succeeded = bool(files_written)
            return ImplementResult(
                attempted=True,
                succeeded=succeeded,
                model=model,
                files_written=files_written,
                llm_response_path=str(llm_path.name),
                implementation_mode="parallel",
                subagents_run=len(parallel.subagents),
                subagents_succeeded=sum(1 for s in parallel.subagents if s.succeeded),
                synthesizer_used=parallel.synthesizer_used,
                skipped_reason=None if succeeded else (parallel.error or "Merge produced no applicable files"),
                error=parallel.error if not succeeded else None,
            )
        except Exception as exc:  # noqa: BLE001
            return ImplementResult(
                attempted=True,
                succeeded=False,
                model=model,
                implementation_mode="parallel",
                error=str(exc),
            )

    def _implement_single(
        self,
        gap: GapItem,
        *,
        cycle_id: int,
        design_brief: str,
        artifact_dir: Path,
        model: str,
    ) -> ImplementResult:
        repo = target_repo()
        context = self._build_context(repo, gap)
        delivery = DeliveryConfig.from_env()
        if delivery.tests_first:
            target_test = suggest_test_path(gap.gap_id, gap.route)
            template_rel = pick_test_template(gap.route or gap.title)
            system = (
                "You write focused pytest files for the AgentHub gateway. "
                "Use TestClient(app) from app.main only. No backend.* imports. No helper functions unless copied from template. "
                + self.FILE_BLOCK_INSTRUCTION
            )
            user = build_tests_first_user_prompt(
                gap=gap,
                cycle_id=cycle_id,
                design_brief=design_brief,
                context=context,
                target_test=target_test,
                template_rel=template_rel,
            )
        else:
            system = (
                "You are a senior gateway platform engineer. "
                "Implement minimal, correct code changes in the target repository. "
                "Follow security, audit, and least-privilege rules from AGENTS.md. "
                + self.FILE_BLOCK_INSTRUCTION
            )
            user = f"""# Implementation task — cycle {cycle_id:04d}

## Gap
- ID: {gap.gap_id}
- Title: {gap.title}
- Route: {gap.route or 'N/A'}
- Coverage: {gap.coverage or 'N/A'}
- Rationale: {gap.rationale}

## Design brief
{design_brief}

## Repository context
Target root: {repo}

{context}

Implement the smallest correct slice for this gap. Output complete files to create or replace.
"""
        try:
            response = self.client.chat(system=system, user=user, label="single_implement")
            llm_path = artifact_dir / "local_llm_response.md"
            llm_path.write_text(response, encoding="utf-8")
            blocks = extract_file_blocks(response)
            blocks = normalize_test_blocks(blocks, gap_id=gap.gap_id, route=gap.route)
            blocks, _dropped = filter_blocks_for_delivery(blocks, repo)
            if not blocks and delivery.tests_first:
                target_test = suggest_test_path(gap.gap_id, gap.route)
                blocks = {target_test: scaffold_auth_test(gap, target_test)}
            if not blocks:
                return ImplementResult(
                    attempted=True,
                    succeeded=False,
                    model=model,
                    implementation_mode="single",
                    skipped_reason="No deliverable blocks after delivery filter",
                )
            pre_apply = SecurityGuardrails().check_blocks(blocks, repo_root=repo)
            if not pre_apply.passed:
                return ImplementResult(
                    attempted=True,
                    succeeded=False,
                    model=model,
                    implementation_mode="single",
                    error="Pre-apply guardrails: " + "; ".join(pre_apply.violations),
                )
            files_written = apply_file_blocks(
                repo,
                "\n\n".join(f"```file:{p}\n{c.rstrip()}\n```" for p, c in sorted(blocks.items())),
                allowed_prefixes=self._allowed_prefixes(),
            )
            return ImplementResult(
                attempted=True,
                succeeded=bool(files_written),
                model=model,
                files_written=files_written,
                llm_response_path=str(llm_path.name),
                implementation_mode="single",
                skipped_reason=None if files_written else "LLM response contained no valid file blocks",
            )
        except Exception as exc:  # noqa: BLE001
            scaffold = self._scaffold_on_failure(gap, cycle_id=cycle_id, artifact_dir=artifact_dir, model=model)
            if scaffold is not None:
                return scaffold
            return ImplementResult(
                attempted=True,
                succeeded=False,
                model=model,
                implementation_mode="single",
                error=str(exc),
            )

    def _scaffold_on_failure(
        self,
        gap: GapItem,
        *,
        cycle_id: int,
        artifact_dir: Path,
        model: str,
    ) -> ImplementResult | None:
        delivery = DeliveryConfig.from_env()
        if not delivery.tests_first or os.environ.get("AGENT_SCAFFOLD_EASY_GAPS", "1") != "1":
            return None
        if not is_auth_only_gap(gap):
            return None
        return self._try_scaffold_first(gap, cycle_id=cycle_id, artifact_dir=artifact_dir, model=model)

    def _context_limits(self) -> tuple[int, int, int]:
        delivery = DeliveryConfig.from_env()
        if delivery.tests_first:
            return (
                self.config.tests_first_max_context_files,
                self.config.tests_first_max_file_chars,
                max(512, self.config.effective_max_prompt_tokens() // 2),
            )
        return (
            self.config.max_context_files,
            self.config.max_file_chars,
            self.config.effective_max_prompt_tokens(),
        )

    def _build_context(self, repo: Path, gap: GapItem) -> str:
        max_files, max_file_chars, max_total_tokens = self._context_limits()
        paths = self._context_paths(repo, gap)

        def _read(rel: str) -> str:
            return read_repo_file(rel) or ""

        return build_context_from_paths(
            paths,
            read_file=_read,
            max_files=max_files,
            max_file_chars=max_file_chars,
            max_total_tokens=max_total_tokens,
        )

    def _context_paths(self, repo: Path, gap: GapItem) -> list[str]:
        delivery = DeliveryConfig.from_env()
        if delivery.tests_first:
            template_rel = pick_test_template(gap.route or gap.title)
            candidates = [
                template_rel,
                "backend/tests/test_gateway_inference.py",
            ]
        else:
            candidates = [
                "backend/AGENTS.md",
                "backend/docs/governance/api-inventory-and-ui-map.md",
                "backend/app/routers/gateway.py",
            ]
        if gap.route:
            route_key = gap.route.strip("/").replace("/", "_")
            candidates.extend(
                [
                    f"backend/tests/test_gateway_{route_key}.py",
                    "backend/tests/test_gateway_routes.py",
                ]
            )
        candidates.extend(["frontend/app.js", "frontend/views/routing-gateway.html"])
        if delivery.tests_first:
            candidates = [c for c in candidates if c.startswith("backend/tests/")]
        seen: set[str] = set()
        ordered: list[str] = []
        for rel in candidates:
            if rel not in seen:
                seen.add(rel)
                ordered.append(rel)
        return ordered
