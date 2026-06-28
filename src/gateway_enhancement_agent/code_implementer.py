"""Apply gateway gap fixes using a local LLM (Ollama CPU/GPU)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.gap_analyzer import GapItem
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient


FILE_BLOCK_RE = re.compile(
    r"```(?:file:?|path:?)\s*([^\n`]+)\n([\s\S]*?)```",
    re.IGNORECASE,
)


@dataclass
class ImplementResult:
    attempted: bool
    succeeded: bool
    model: str | None = None
    files_written: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    error: str | None = None
    llm_response_path: str | None = None


class CodeImplementer:
    def __init__(self, config: LLMConfig | None = None, client: LocalLLMClient | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.client = client or LocalLLMClient(self.config)

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

        repo = target_repo()
        context = self._build_context(repo, gap)
        system = (
            "You are a senior gateway platform engineer. "
            "Implement minimal, correct code changes in the target repository. "
            "Follow security, audit, and least-privilege rules from AGENTS.md. "
            "Respond ONLY with one or more file blocks in this exact format:\n"
            "```file:backend/path/to/file.py\n"
            "<full file contents>\n"
            "```\n"
            "Use paths relative to the repository root. Do not include secrets or .env files."
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
            response = self.client.chat(system=system, user=user)
            llm_path = artifact_dir / "local_llm_response.md"
            llm_path.write_text(response, encoding="utf-8")
            files_written = self._apply_file_blocks(repo, response)
            return ImplementResult(
                attempted=True,
                succeeded=bool(files_written),
                model=health.model,
                files_written=files_written,
                llm_response_path=str(llm_path.relative_to(artifact_dir.parent.parent)),
                skipped_reason=None if files_written else "LLM response contained no valid file blocks",
            )
        except Exception as exc:  # noqa: BLE001
            return ImplementResult(
                attempted=True,
                succeeded=False,
                model=health.model,
                error=str(exc),
            )

    def _build_context(self, repo: Path, gap: GapItem) -> str:
        paths = self._context_paths(repo, gap)
        chunks: list[str] = []
        for rel in paths[: self.config.max_context_files]:
            full = repo / rel
            if not full.is_file():
                continue
            text = full.read_text(encoding="utf-8", errors="replace")
            if len(text) > self.config.max_file_chars:
                text = text[: self.config.max_file_chars] + "\n... [truncated]"
            chunks.append(f"### `{rel}`\n```\n{text}\n```")
        if not chunks:
            return "_No context files found._"
        return "\n\n".join(chunks)

    def _context_paths(self, repo: Path, gap: GapItem) -> list[str]:
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
        seen: set[str] = set()
        ordered: list[str] = []
        for rel in candidates:
            if rel not in seen:
                seen.add(rel)
                ordered.append(rel)
        return ordered

    def _apply_file_blocks(self, repo: Path, response: str) -> list[str]:
        written: list[str] = []
        for match in FILE_BLOCK_RE.finditer(response):
            rel = match.group(1).strip().lstrip("./")
            content = match.group(2)
            if not self._allowed_path(rel):
                continue
            dest = (repo / rel).resolve()
            if not str(dest).startswith(str(repo.resolve())):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
            written.append(rel)
        return written

    def _allowed_path(self, rel: str) -> bool:
        if ".." in Path(rel).parts:
            return False
        return any(rel.startswith(prefix) for prefix in self.config.allowed_path_prefixes)
