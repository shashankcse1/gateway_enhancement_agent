from __future__ import annotations

from gateway_enhancement_agent.security_guardrails import SecurityGuardrails, parse_review_verdict


def test_parse_review_verdict_explicit_approve() -> None:
    text = "## Findings\nSome notes about BLOCKER usage in docs.\n\nVerdict: APPROVE\n"
    assert parse_review_verdict(text) == "APPROVE"


def test_parse_review_verdict_explicit_blocker() -> None:
    text = "## Summary\nRisky change.\n\n**Verdict: BLOCKER**\n"
    assert parse_review_verdict(text) == "BLOCKER"


def test_check_reviews_ignores_blocker_mentions_without_verdict() -> None:
    guard = SecurityGuardrails()
    reviews = {
        "ciso_lens": "Use BLOCKER only for production-safety issues. Findings look fine. Verdict: APPROVE",
    }
    result = guard.check_reviews(reviews)
    assert result.passed is True
    assert not result.violations


def test_check_reviews_blocks_mandatory_explicit_blocker() -> None:
    guard = SecurityGuardrails()
    reviews = {
        "ciso_lens": "Summary\nFindings\nRisk level: HIGH\nVerdict: BLOCKER",
    }
    result = guard.check_reviews(reviews)
    assert result.passed is False
    assert any("ciso_lens" in v for v in result.violations)


def test_check_blocks_rejects_syntax_error(tmp_path) -> None:
    guard = SecurityGuardrails()
    result = guard.check_blocks(
        {"backend/tests/test_bad.py": "def broken(\n"},
        repo_root=tmp_path,
    )
    assert result.passed is False
    assert any("syntax" in v.lower() for v in result.violations)


def test_check_blocks_rejects_truncated_governance_shrink(tmp_path) -> None:
    guard = SecurityGuardrails()
    gov = tmp_path / "backend/docs/governance/api-inventory-and-ui-map.md"
    gov.parent.mkdir(parents=True)
    gov.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
    short = "# shrunk\n\nonly a few lines\n"
    result = guard.check_blocks(
        {"backend/docs/governance/api-inventory-and-ui-map.md": short},
        repo_root=tmp_path,
    )
    assert result.passed is False
    assert any("shrinks" in v.lower() for v in result.violations)


def test_check_blocks_rejects_truncated_gateway(tmp_path) -> None:
    guard = SecurityGuardrails()
    short = "from fastapi import APIRouter\nrouter = APIRouter()\n"
    result = guard.check_blocks(
        {"backend/app/routers/gateway.py": short},
        repo_root=tmp_path,
    )
    assert result.passed is False
    assert any("truncated" in v.lower() or "only" in v.lower() for v in result.violations)
