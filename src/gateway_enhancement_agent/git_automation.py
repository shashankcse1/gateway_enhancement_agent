"""Autonomous git commit, merge, and push for TARGET_REPO."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from gateway_enhancement_agent.config import config_dir, load_json, target_repo
from gateway_enhancement_agent.gap_models import GapItem


@dataclass
class AutonomousConfig:
    enabled: bool
    auto_push: bool
    merge_branch: str
    branch_prefix: str
    rollback_on_validation_failure: bool
    exclude_paths: list[str]
    push_remotes: list[str]

    @classmethod
    def from_env(cls) -> AutonomousConfig:
        raw = load_json("autonomous.json")
        env_on = os.environ.get("AGENT_FULLY_AUTONOMOUS", "").strip().lower()
        enabled = raw.get("enabled", False)
        if env_on in {"1", "true", "yes"}:
            enabled = True
        elif env_on in {"0", "false", "no"}:
            enabled = False
        auto_push = bool(raw.get("auto_push", False))
        push_env = os.environ.get("AGENT_AUTO_PUSH", "").strip().lower()
        if push_env in {"1", "true", "yes"}:
            auto_push = True
        elif push_env in {"0", "false", "no"}:
            auto_push = False
        merge_branch = os.environ.get("AGENT_MERGE_BRANCH", raw.get("merge_branch", "")).strip()
        push_remotes = list(raw.get("push_remotes", ["bitbucket", "origin"]))
        env_remotes = os.environ.get("GIT_PUSH_REMOTES", "").strip()
        if env_remotes:
            push_remotes = [r.strip() for r in env_remotes.split(",") if r.strip()]
        return cls(
            enabled=enabled,
            auto_push=auto_push,
            merge_branch=merge_branch,
            branch_prefix=raw.get("branch_prefix", "agent/cycle-"),
            rollback_on_validation_failure=bool(raw.get("rollback_on_validation_failure", True)),
            exclude_paths=list(raw.get("exclude_paths", [])),
            push_remotes=push_remotes,
        )


def fully_autonomous() -> bool:
    return AutonomousConfig.from_env().enabled


@dataclass
class MergeResult:
    attempted: bool
    succeeded: bool
    commit_sha: str | None = None
    feature_branch: str | None = None
    merge_branch: str | None = None
    pushed: bool = False
    push_ref: str | None = None
    files_committed: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    error: str | None = None


class GitAutomator:
    def __init__(self, repo: Path | None = None, config: AutonomousConfig | None = None) -> None:
        self.repo = (repo or target_repo()).resolve()
        self.config = config or AutonomousConfig.from_env()

    def commit_and_merge(
        self,
        *,
        gap: GapItem,
        cycle_id: int,
        files_written: list[str],
        start_branch: str,
    ) -> MergeResult:
        if not self.config.enabled:
            return MergeResult(attempted=False, succeeded=False, skipped_reason="Autonomous mode disabled")
        if not files_written:
            return MergeResult(attempted=False, succeeded=False, skipped_reason="No files to commit")
        if not (self.repo / ".git").exists():
            return MergeResult(attempted=False, succeeded=False, skipped_reason="TARGET_REPO is not a git repository")

        feature_branch = f"{self.config.branch_prefix}{cycle_id:04d}"
        merge_branch = self.config.merge_branch or start_branch
        message = (
            f"agent: close {gap.gap_id} — {gap.title}\n\n"
            f"Autonomous enhancement cycle {cycle_id:04d}.\n"
            f"Gap score: {gap.score}. Source: {gap.source}."
        )
        try:
            self._run("git", "rev-parse", "--is-inside-work-tree")
            self._ensure_clean_enough()
            self._run("git", "checkout", "-b", feature_branch)
            staged = self._stage_files(files_written)
            if not staged:
                self._run("git", "checkout", start_branch)
                self._run("git", "branch", "-D", feature_branch)
                return MergeResult(
                    attempted=True,
                    succeeded=False,
                    feature_branch=feature_branch,
                    error="No staged changes after implementation",
                )
            self._run("git", "commit", "-m", message)
            commit_sha = self._run("git", "rev-parse", "HEAD").stdout.strip()
            self._run("git", "checkout", merge_branch)
            self._run("git", "merge", "--no-edit", feature_branch)
            pushed = False
            push_ref = None
            push_errors: list[str] = []
            if self.config.auto_push:
                for remote in self.config.push_remotes:
                    try:
                        self._run("git", "push", remote, feature_branch)
                        self._run("git", "push", remote, merge_branch)
                    except GitCommandError as exc:
                        push_errors.append(f"{remote}: {exc}")
                pushed = not push_errors
                push_ref = merge_branch if pushed else None
            if push_errors and not pushed:
                return MergeResult(
                    attempted=True,
                    succeeded=False,
                    commit_sha=commit_sha,
                    feature_branch=feature_branch,
                    merge_branch=merge_branch,
                    pushed=False,
                    files_committed=staged,
                    error="; ".join(push_errors),
                )
            return MergeResult(
                attempted=True,
                succeeded=True,
                commit_sha=commit_sha,
                feature_branch=feature_branch,
                merge_branch=merge_branch,
                pushed=pushed,
                push_ref=push_ref,
                files_committed=staged,
            )
        except GitCommandError as exc:
            self._safe_checkout(start_branch)
            return MergeResult(
                attempted=True,
                succeeded=False,
                feature_branch=feature_branch,
                merge_branch=merge_branch,
                error=str(exc),
            )

    def rollback(self, files_written: list[str], start_branch: str) -> None:
        if not files_written or not (self.repo / ".git").exists():
            return
        try:
            for rel in files_written:
                self._run("git", "checkout", "--", rel, check=False)
            self._safe_checkout(start_branch)
        except GitCommandError:
            return

    def current_branch(self) -> str:
        return self._run("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def _ensure_clean_enough(self) -> None:
        status = self._run("git", "status", "--porcelain").stdout.splitlines()
        blocked = [
            line[3:]
            for line in status
            if len(line) >= 4 and not any(line[3:].startswith(ex) for ex in self.config.exclude_paths)
        ]
        # Allow modifications only in backend/ and frontend/ for autonomous flow
        disallowed = [p for p in blocked if not (p.startswith("backend/") or p.startswith("frontend/"))]
        if disallowed:
            raise GitCommandError(
                f"Refusing autonomous merge with unrelated dirty files: {', '.join(disallowed[:5])}"
            )

    def _stage_files(self, files_written: list[str]) -> list[str]:
        staged: list[str] = []
        for rel in files_written:
            path = self.repo / rel
            if not path.exists():
                continue
            self._run("git", "add", "--", rel)
            staged.append(rel)
        diff = self._run("git", "diff", "--cached", "--name-only").stdout.strip()
        if diff:
            staged = sorted(set(staged + [line for line in diff.splitlines() if line]))
        return staged

    def _safe_checkout(self, branch: str) -> None:
        self._run("git", "checkout", branch, check=False)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            list(args),
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise GitCommandError(f"{' '.join(args)} failed: {detail}")
        return proc


class GitCommandError(RuntimeError):
    pass


def merge_report_markdown(result: MergeResult, gap: GapItem, cycle_id: int) -> str:
    if not result.attempted:
        return f"# Autonomous Merge — Cycle {cycle_id:04d}\n\nSkipped: {result.skipped_reason}\n"
    status = "SUCCESS" if result.succeeded else "FAILED"
    files = "\n".join(f"- `{f}`" for f in result.files_committed) or "- _(none)_"
    return f"""# Autonomous Merge — Cycle {cycle_id:04d}

## Gap

**{gap.title}** (`{gap.gap_id}`)

## Status

**{status}**

## Git

- Feature branch: `{result.feature_branch or '—'}`
- Merge target: `{result.merge_branch or '—'}`
- Commit: `{result.commit_sha or '—'}`
- Pushed: **{'yes' if result.pushed else 'no'}** {f'(`{result.push_ref}`)' if result.push_ref else ''}

## Files committed

{files}

{f'## Error{chr(10)}{chr(10)}{result.error}' if result.error else ''}
"""


def merge_report_json(result: MergeResult) -> dict:
    return {
        "attempted": result.attempted,
        "succeeded": result.succeeded,
        "commit_sha": result.commit_sha,
        "feature_branch": result.feature_branch,
        "merge_branch": result.merge_branch,
        "pushed": result.pushed,
        "push_ref": result.push_ref,
        "files_committed": result.files_committed,
        "skipped_reason": result.skipped_reason,
        "error": result.error,
    }
