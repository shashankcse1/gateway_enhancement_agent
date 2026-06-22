from __future__ import annotations

from gateway_enhancement_agent.sdlc_validate import (
    CombinedValidation,
    combined_report_markdown,
    combined_summary,
)
from gateway_enhancement_agent.validation_runner import GateResult


def test_combined_summary_pass_fail() -> None:
    passed = GateResult("a", "A", True, True, 0, "", "")
    failed = GateResult("b", "B", True, False, 1, "", "err")
    combined = CombinedValidation(self_results=[passed], target_results=[failed])
    summary = combined_summary(combined)
    assert summary["passed"] is False
    assert summary["self_test_passed"] is True
    assert summary["target_validation_passed"] is False


def test_combined_report_includes_both_layers() -> None:
    combined = CombinedValidation(
        self_results=[GateResult("agent_unit_tests", "Agent tests", True, True, 0, "", "")],
        target_results=[GateResult("gateway_pytest", "Gateway pytest", True, True, 0, "", "")],
    )
    md = combined_report_markdown(combined)
    assert "Agent self-tests" in md
    assert "Target repo gates" in md
    assert "PASS" in md
