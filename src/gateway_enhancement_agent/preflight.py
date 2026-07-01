"""Pre-flight checks before autonomous SDLC cycles."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.git_automation import GitAutomator
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient
from gateway_enhancement_agent.mirror_sync import sync_mirror


def run_preflight() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    ok = True

    def add(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        if not passed:
            ok = False
        checks.append({"name": name, "passed": passed, "detail": detail})

    repo: Path | None = None
    try:
        repo = target_repo()
        add("target_repo", repo.is_dir(), str(repo))
    except FileNotFoundError as exc:
        add("target_repo", False, str(exc))

    if repo and (repo / ".git").is_dir():
        try:
            branch = GitAutomator(repo).current_branch()
            add("git_repo", True, f"branch={branch}")
        except Exception as exc:  # noqa: BLE001
            add("git_repo", False, str(exc))
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        add("git_remote", proc.returncode == 0, (proc.stdout or proc.stderr).strip())

    proc = subprocess.run([sys.executable, "-m", "pytest", "--version"], capture_output=True, text=True, timeout=15)
    add("agent_pytest", proc.returncode == 0, (proc.stdout or proc.stderr).strip())

    gateway_py = os.environ.get("GATEWAY_PYTHON", "").strip()
    if gateway_py:
        add("gateway_python", Path(gateway_py).is_file(), gateway_py)
    elif repo:
        venv = repo / "backend" / ".venv" / "bin" / "python"
        add("gateway_venv", venv.is_file(), str(venv) if venv.is_file() else "set GATEWAY_PYTHON or create backend/.venv")

    cfg = LLMConfig.from_env()
    if cfg.auto_implement:
        health = LocalLLMClient(cfg).health()
        add("ollama", health.reachable and health.model_available, health.error or health.model)
    else:
        add("ollama", True, "LOCAL_LLM_AUTO_IMPLEMENT=0")

    config_dir = os.environ.get("AGENT_CONFIG_DIR", "")
    add("agent_config_dir", bool(config_dir and Path(config_dir).is_dir()), config_dir or "unset")

    if repo:
        try:
            result = sync_mirror(repo)
            add("mirror_sync", True, f"{len(result.get('files_copied', []))} files")
        except OSError as exc:
            add("mirror_sync", False, str(exc))

    source = os.environ.get("TARGET_REPO_SOURCE", "").strip()
    if source:
        add("source_repo_set", Path(source).expanduser().is_dir(), source)

    return {"ok": ok, "checks": checks}


def preflight_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent preflight",
        "",
        f"Overall: **{'PASS' if report.get('ok') else 'FAIL'}**",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for check in report.get("checks", []):
        status = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"| {check.get('name')} | {status} | {str(check.get('detail', ''))[:80]} |")
    return "\n".join(lines) + "\n"
