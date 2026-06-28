from __future__ import annotations

from gateway_enhancement_agent.weekly_summary import build_weekly_summary, weekly_summary_markdown


def test_weekly_summary_contains_inventory(mock_target_repo) -> None:
    summary = build_weekly_summary()
    text = weekly_summary_markdown(summary)
    assert summary["inventory"]["gateway_routes"] >= 1
    assert "Gateway Agent Summary" in text
    assert "Gap matrix" in text
    assert "Capability coverage matrix" in text
    assert "Agent performance" in text
    assert summary.get("gap_matrix")
    assert summary.get("capability_matrix")
    assert summary.get("performance")
    assert summary["target_repo"] == str(mock_target_repo)


def test_weekly_summary_subject(mock_target_repo) -> None:
    from gateway_enhancement_agent.weekly_summary import weekly_summary_subject

    summary = build_weekly_summary()
    subject = weekly_summary_subject(summary)
    assert "[Gateway Agent]" in subject
    assert "Summary" in subject
