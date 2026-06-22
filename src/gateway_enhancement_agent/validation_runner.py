"""Run validation gates in TARGET_REPO via subprocess (local only)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import load_json, target_repo


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
    def __init__(self, repo: Path | None = None) -> None:
        self.repo = repo or target_repo()
        self.config = load_json("validation_gates.json")

    def run_all(self) -> list[GateResult]:
        results: list[GateResult] = []
        for gate in self.config.get("gates", []):
            results.append(self._run_gate(gate))
        return results

    def _run_gate(self, gate: dict[str, Any]) -> GateResult:
        cwd = self.repo / gate.get("cwd", ".")
        command = list(gate["command"])
        timeout = int(gate.get("timeout_seconds", 300))
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            passed = proc.returncode == 0
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
