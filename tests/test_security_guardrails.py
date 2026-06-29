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
