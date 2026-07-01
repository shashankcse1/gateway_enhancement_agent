from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.git_automation import AutonomousConfig, GitAutomator, GitCommandError


def _gap() -> GapItem:
    return GapItem(
        gap_id="inv-001",
        title="DELETE /v1/responses/{id}",
        source="api_inventory",
        priority=1,
        score=10,
        route="/v1/responses/{id}",
        coverage="Gap",
    )


def test_commit_and_merge_stages_test_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    test_file = repo / "backend" / "tests" / "test_gateway_delete_v1_responses_id.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("assert True\n", encoding="utf-8")

    def fake_run(*args: str, check: bool = True):
        cmd = " ".join(args)
        proc = MagicMock()
        proc.returncode = 0
        if args[:2] == ("git", "rev-parse") and args[-1] == "HEAD":
            proc.stdout = "abc123def456\n"
        elif args[:2] == ("git", "rev-parse"):
            proc.stdout = "true\n"
        elif args[:2] == ("git", "status"):
            proc.stdout = ""
        elif args[:2] == ("git", "diff"):
            proc.stdout = "backend/tests/test_gateway_delete_v1_responses_id.py\n"
        else:
            proc.stdout = ""
        proc.stderr = ""
        if check and proc.returncode != 0:
            raise GitCommandError(cmd)
        return proc

    cfg = AutonomousConfig(
        enabled=True,
        auto_push=False,
        merge_branch="",
        branch_prefix="agent/cycle-",
        rollback_on_validation_failure=True,
        exclude_paths=[".env"],
        push_remotes=["origin"],
        push_retries=1,
        push_retry_delay_seconds=0,
        pull_before_branch=False,
    )
    automator = GitAutomator(repo, cfg)
    commit_messages: list[str] = []
    real_fake = fake_run

    def tracking_run(*args: str, check: bool = True):
        if len(args) >= 4 and args[0] == "git" and args[1] == "commit" and args[2] == "-m":
            commit_messages.append(args[3])
        return real_fake(*args, check=check)

    with patch.object(automator, "_run", side_effect=tracking_run):
        result = automator.commit_and_merge(
            gap=_gap(),
            cycle_id=42,
            files_written=["backend/tests/test_gateway_delete_v1_responses_id.py"],
            start_branch="main",
        )
    assert result.succeeded is True
    assert result.commit_sha == "abc123def456"
    assert "backend/tests/test_gateway_delete_v1_responses_id.py" in result.files_committed
    assert commit_messages
    assert "agent(tests): cover inv-001 — DELETE /v1/responses/{id}" in commit_messages[0]


def test_rollback_restores_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    calls: list[str] = []

    def fake_run(*args: str, check: bool = True):
        calls.append(" ".join(args))
        proc = MagicMock(returncode=0, stdout="", stderr="")
        return proc

    automator = GitAutomator(repo, AutonomousConfig.from_env())
    with patch.object(automator, "_run", side_effect=fake_run):
        automator.rollback(["backend/tests/x.py"], "main")
    assert any("checkout" in c for c in calls)
