"""Run validation gates in TARGET_REPO via subprocess (local only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import load_json, source_root, target_repo
from gateway_enhancement_agent.progress_log import log

_DEFAULT_TOOL_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


@dataclass
class GateResult:
    gate_id: str
    label: str
    required: bool
    passed: bool
    returncode: int
    stdout_tail: str
    stderr_tail: str


class ValidationRunner:
    def __init__(self, repo: Path | None = None, config_name: str = "validation_gates.json") -> None:
        self.repo = repo or target_repo()
        self.config = load_json(config_name)

    def run_all(self, *, changed_files: list[str] | None = None) -> list[GateResult]:
        results: list[GateResult] = []
        for gate in self.config.get("gates", []):
            results.append(self._run_gate(gate, changed_files=changed_files))
        return results

    def _run_gate(self, gate: dict[str, Any], *, changed_files: list[str] | None = None) -> GateResult:
        gate_id = gate.get("id", "")
        if changed_files:
            if gate_id == "frontend_syntax" and not any(f.startswith("frontend/") for f in changed_files):
                log(f"gate {gate_id}: skipped (no frontend files changed)", phase="validate")
                return GateResult(
                    gate_id=gate_id,
                    label=gate["label"],
                    required=bool(gate.get("required", True)),
                    passed=True,
                    returncode=0,
                    stdout_tail="skipped (no frontend files changed)",
                    stderr_tail="",
                )
            if gate_id == "security_smoke" and not any(f.startswith("frontend/") for f in changed_files):
                log(f"gate {gate_id}: skipped (no frontend files changed)", phase="validate")
                return GateResult(
                    gate_id=gate_id,
                    label=gate["label"],
                    required=bool(gate.get("required", True)),
                    passed=True,
                    returncode=0,
                    stdout_tail="skipped (no frontend files changed)",
                    stderr_tail="",
                )
        cwd_rel = gate.get("cwd", ".")
        if gate_id == "agent_unit_tests":
            # launchd runs from /tmp; Desktop-linked source_root may be TCC-blocked as cwd.
            cwd = Path(os.environ.get("AGENT_DATA_DIR", "/tmp"))
            tests_dir = source_root() / "tests"
            command = [self._python_for_cwd(cwd), "-m", "pytest", "-q", str(tests_dir)]
        else:
            cwd = self.repo if cwd_rel == "." else self.repo / cwd_rel
            command = self._resolve_command(list(gate["command"]), cwd=cwd, changed_files=changed_files)
        timeout = int(gate.get("timeout_seconds", 300))
        log(f"gate {gate_id}: {gate.get('label', gate_id)}", phase="validate")
        env = os.environ.copy()
        prefix = os.environ.get("AGENT_TOOL_PATH", _DEFAULT_TOOL_PATH)
        env["PATH"] = f"{prefix}:{env.get('PATH', '')}"
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            passed = proc.returncode == 0
            log(
                f"gate {gate_id}: {'PASS' if passed else 'FAIL'} (exit {proc.returncode})",
                phase="validate",
            )
            return GateResult(
                gate_id=gate["id"],
                label=gate["label"],
                required=bool(gate.get("required", True)),
                passed=passed,
                returncode=proc.returncode,
                stdout_tail=(proc.stdout or "")[-2000:],
                stderr_tail=(proc.stderr or "")[-2000:],
            )
        except subprocess.TimeoutExpired as exc:
            log(f"gate {gate_id}: TIMEOUT after {timeout}s", phase="validate")
            return GateResult(
                gate_id=gate["id"],
                label=gate["label"],
                required=bool(gate.get("required", True)),
                passed=False,
                returncode=-1,
                stdout_tail=(exc.stdout or "")[-2000:] if exc.stdout else "",
                stderr_tail=f"Timed out after {timeout}s",
            )
        except FileNotFoundError as exc:
            return GateResult(
                gate_id=gate["id"],
                label=gate["label"],
                required=bool(gate.get("required", True)),
                passed=False,
                returncode=-1,
                stdout_tail="",
                stderr_tail=str(exc),
            )

    def summary(self, results: list[GateResult]) -> dict[str, Any]:
        required_failures = [r for r in results if r.required and not r.passed]
        return {
            "passed": len(required_failures) == 0,
            "total": len(results),
            "required_failures": [r.gate_id for r in required_failures],
            "results": [
                {
                    "gate_id": r.gate_id,
                    "label": r.label,
                    "required": r.required,
                    "passed": r.passed,
                    "returncode": r.returncode,
                }
                for r in results
            ],
        }

    def report_markdown(self, results: list[GateResult]) -> str:
        summary = self.summary(results)
        lines = [
            "# Validation Report",
            "",
            f"Overall: **{'PASS' if summary['passed'] else 'FAIL'}**",
            "",
            "| Gate | Required | Result |",
            "| --- | --- | --- |",
        ]
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"| {r.label} | {'yes' if r.required else 'no'} | {status} |")
        failures = [r for r in results if not r.passed]
        if failures:
            lines.extend(["", "## Failure details", ""])
            for r in failures:
                lines.append(f"### {r.gate_id}")
                if r.stderr_tail:
                    lines.append("```")
                    lines.append(r.stderr_tail.strip())
                    lines.append("```")
        return "\n".join(lines) + "\n"

    def write_json_report(self, path: Path, results: list[GateResult]) -> None:
        payload = self.summary(results)
        payload["details"] = [
            {
                "gate_id": r.gate_id,
                "stdout_tail": r.stdout_tail,
                "stderr_tail": r.stderr_tail,
            }
            for r in results
            if not r.passed
        ]
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _resolve_command(self, command: list[str], *, cwd: Path, changed_files: list[str] | None = None) -> list[str]:
        python_bin = self._python_for_cwd(cwd)
        resolved: list[str] = []
        for part in command:
            if part == "python3":
                resolved.append(python_bin)
            else:
                resolved.append(part)
        if not changed_files or "pytest" not in resolved or "-m" not in resolved:
            return resolved
        test_files = [f for f in changed_files if f.startswith("backend/tests/") and f.endswith(".py")]
        only_tests = test_files and not any(
            f for f in changed_files if f.startswith("backend/") and not f.startswith("backend/tests/")
        )
        if not only_tests:
            return resolved
        # Gate cwd is usually backend/; pytest paths must be tests/..., not backend/tests/...
        scoped_tests = [f.removeprefix("backend/") for f in test_files]
        m_idx = resolved.index("-m")
        first_test_idx = m_idx + 2
        while first_test_idx < len(resolved) and not resolved[first_test_idx].startswith("tests/"):
            first_test_idx += 1
        if first_test_idx < len(resolved):
            resolved = resolved[:first_test_idx] + scoped_tests
        return resolved

    def _python_for_cwd(self, cwd: Path) -> str:
        override = os.environ.get("GATEWAY_PYTHON", "").strip()
        if override:
            return override
        if self.repo.resolve() == source_root().resolve():
            return sys.executable
        repo_root = target_repo().resolve()
        venv_py = repo_root / "backend" / ".venv" / "bin" / "python"
        if venv_py.is_file():
            return str(venv_py)
        return sys.executable
