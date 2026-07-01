"""Combined self-test + target-repo validation for SDLC."""

from __future__ import annotations

from dataclasses import dataclass

from gateway_enhancement_agent.self_test_runner import SelfTestRunner
from gateway_enhancement_agent.validation_runner import GateResult, ValidationRunner


@dataclass
class CombinedValidation:
    self_results: list[GateResult]
    target_results: list[GateResult]

    @property
    def all_results(self) -> list[GateResult]:
        return self.self_results + self.target_results

    @property
    def passed(self) -> bool:
        required = [r for r in self.all_results if r.required]
        return all(r.passed for r in required)


def run_combined_validation(*, changed_files: list[str] | None = None) -> CombinedValidation:
    self_runner = SelfTestRunner()
    target_runner = ValidationRunner()
    return CombinedValidation(
        self_results=self_runner.run_all(),
        target_results=target_runner.run_all(changed_files=changed_files),
    )


def combined_report_markdown(combined: CombinedValidation) -> str:
    lines = [
        "# SDLC Validation Report",
        "",
        f"Overall: **{'PASS' if combined.passed else 'FAIL'}**",
        "",
        "## Agent self-tests",
        "",
        "| Gate | Required | Result |",
        "| --- | --- | --- |",
    ]
    for r in combined.self_results:
        lines.append(f"| {r.label} | {'yes' if r.required else 'no'} | {'PASS' if r.passed else 'FAIL'} |")
    lines.extend(["", "## Target repo gates", "", "| Gate | Required | Result |", "| --- | --- | --- |"])
    for r in combined.target_results:
        lines.append(f"| {r.label} | {'yes' if r.required else 'no'} | {'PASS' if r.passed else 'FAIL'} |")
    failures = [r for r in combined.all_results if not r.passed]
    if failures:
        lines.extend(["", "## Failure details", ""])
        for r in failures:
            lines.append(f"### {r.gate_id}")
            if r.stderr_tail:
                lines.append("```")
                lines.append(r.stderr_tail.strip()[:1500])
                lines.append("```")
    return "\n".join(lines) + "\n"


def combined_summary(combined: CombinedValidation) -> dict:
    return {
        "passed": combined.passed,
        "self_test_passed": all(r.passed for r in combined.self_results if r.required),
        "target_validation_passed": all(r.passed for r in combined.target_results if r.required),
        "self_results": [
            {"gate_id": r.gate_id, "passed": r.passed, "required": r.required} for r in combined.self_results
        ],
        "target_results": [
            {"gate_id": r.gate_id, "passed": r.passed, "required": r.required} for r in combined.target_results
        ],
    }
