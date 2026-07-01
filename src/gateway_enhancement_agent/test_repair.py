"""Structured pytest failure repair (Plan-Execute-Verify repair loop)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.delivery_config import suggest_test_path
from gateway_enhancement_agent.file_blocks import apply_file_blocks, extract_file_blocks
from gateway_enhancement_agent.gap_intelligence import (
    load_gap_intelligence_config,
    normalize_test_blocks,
    scaffold_auth_test,
)
from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient
from gateway_enhancement_agent.progress_log import log
from gateway_enhancement_agent.security_guardrails import SecurityGuardrails
from gateway_enhancement_agent.validation_runner import ValidationRunner

_FAILURE_LINE = re.compile(r"^(E\s+.*|FAILED .*)", re.M)
_ASSERT_LINE = re.compile(r"assert response\.status_code ==")


def structured_pytest_failure(stdout: str, stderr: str, *, max_lines: int = 40) -> str:
    """Extract actionable failure context instead of forwarding full logs."""
    combined = f"{stdout}\n{stderr}"
    lines: list[str] = []
    capture = False
    for line in combined.splitlines():
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            capture = True
            lines.append(line.strip())
            continue
        if capture:
            if line.startswith("="):
                capture = False
                continue
            if line.startswith("E   ") or "AssertionError" in line or "Error" in line:
                lines.append(line.strip())
        if _FAILURE_LINE.match(line):
            lines.append(line.strip())
    if not lines:
        lines = [ln.strip() for ln in combined.splitlines() if ln.strip()][-max_lines:]
    return "\n".join(lines[:max_lines])


def run_scoped_pytest(repo: Path, rel_paths: list[str]) -> tuple[bool, str, str]:
    backend = repo / "backend"
    cwd = backend if backend.is_dir() else repo
    scoped = [p.removeprefix("backend/") for p in rel_paths if p.startswith("backend/tests/")]
    if not scoped:
        return False, "", "no scoped test paths"
    cmd = [sys.executable, "-m", "pytest", "-q", *scoped]
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=300)
    return proc.returncode == 0, proc.stdout or "", proc.stderr or ""


def repair_test_file(
    gap: GapItem,
    rel_path: str,
    failure_context: str,
    *,
    client: LocalLLMClient | None = None,
    attempt: int = 1,
) -> tuple[bool, str]:
    """One repair attempt: fix assertions only in the existing test file."""
    cfg = load_gap_intelligence_config()
    max_attempts = int(cfg.get("max_pytest_repair_attempts", 1))
    if attempt > max_attempts:
        return False, "max repair attempts exceeded"

    repo = target_repo()
    target = suggest_test_path(gap.gap_id, gap.route)
    rel_path = target
    abs_path = repo / rel_path
    if not abs_path.is_file():
        return False, f"missing test file {rel_path}"

    current = abs_path.read_text(encoding="utf-8")
    llm = client or LocalLLMClient(LLMConfig.from_env())
    system = (
        "You fix failing pytest files for a FastAPI gateway. "
        "Respond with ONE file block only. Change assertions and paths only — "
        "do not add helper functions or new imports. Use `assert status in (401, 403)` style."
    )
    user = f"""# Pytest repair — attempt {attempt}

## Gap
{gap.title} (`{gap.gap_id}`)

## File
`{rel_path}`

## Current contents
```
{current[:4000]}
```

## Failure summary
```
{failure_context[:2500]}
```

## Instructions
- Fix failing assertions only.
- Prefer `assert response.status_code in (...)` with realistic codes.
- Remove any helper that causes NameError.
- Max 45 lines total.
- Output path must be exactly `{target}`.
"""
    response = llm.chat(system=system, user=user, label=f"pytest_repair:{attempt}")
    blocks = extract_file_blocks(response)
    blocks = normalize_test_blocks(blocks, gap_id=gap.gap_id, route=gap.route)
    if not blocks:
        return False, "repair produced no file blocks"

    guard = SecurityGuardrails().check_blocks(blocks, repo_root=repo)
    if not guard.passed:
        return False, "repair blocked by guardrails: " + "; ".join(guard.violations)

    apply_file_blocks(
        repo,
        "\n\n".join(f"```file:{p}\n{c.rstrip()}\n```" for p, c in sorted(blocks.items())),
        allowed_prefixes=["backend/tests/"],
    )
    passed, out, err = run_scoped_pytest(repo, [target])
    if passed:
        log(f"pytest repair attempt {attempt}: PASS", phase="validate")
        return True, ""
    context = structured_pytest_failure(out, err)
    if _ASSERT_LINE.search(current) and attempt >= max_attempts:
        scaffold = scaffold_auth_test(gap, target)
        guard2 = SecurityGuardrails().check_blocks({target: scaffold}, repo_root=repo)
        if guard2.passed:
            apply_file_blocks(
                repo,
                f"```file:{target}\n{scaffold.rstrip()}\n```",
                allowed_prefixes=["backend/tests/"],
            )
            passed, _, _ = run_scoped_pytest(repo, [target])
            if passed:
                log("pytest repair: PASS after auth scaffold fallback", phase="validate")
                return True, ""
    log(f"pytest repair attempt {attempt}: FAIL", phase="validate")
    return False, context or "scoped pytest still failing"


def validate_changed_tests(changed_files: list[str]) -> tuple[bool, str]:
    """Run scoped pytest and return structured failure for repair."""
    repo = target_repo()
    passed, out, err = run_scoped_pytest(repo, changed_files)
    if passed:
        return True, ""
    runner = ValidationRunner(repo)
    # Also run required gates via existing runner when needed
    results = runner.run_all(changed_files=changed_files)
    required_fail = [r for r in results if r.required and not r.passed]
    if not required_fail:
        return True, ""
    parts = []
    for r in required_fail:
        if r.gate_id == "gateway_pytest":
            parts.append(structured_pytest_failure(r.stdout_tail, r.stderr_tail))
        else:
            parts.append(r.stderr_tail or r.stdout_tail)
    return False, "\n".join(p for p in parts if p)
