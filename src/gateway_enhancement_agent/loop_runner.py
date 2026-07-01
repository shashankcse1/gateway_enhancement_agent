"""Continuous local competitor-check loop with failure backoff."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from gateway_enhancement_agent.config import load_json, runtime_dir
from gateway_enhancement_agent.email_notifier import maybe_send_weekly_report
from gateway_enhancement_agent.git_automation import fully_autonomous
from gateway_enhancement_agent.progress_log import log
from gateway_enhancement_agent.sdlc_pipeline import SDLCPipeline
from gateway_enhancement_agent.state_store import CycleState


def _background_mode() -> bool:
    return os.environ.get("AGENT_BACKGROUND_MODE", "").strip().lower() in {"1", "true", "yes"}


def _loop_policy() -> dict:
    try:
        return load_json("loop_policy.json")
    except FileNotFoundError:
        return {}


def _backoff_state_path() -> Path:
    return runtime_dir() / "loop_backoff.json"


def _load_backoff() -> dict:
    path = _backoff_state_path()
    if not path.exists():
        return {"consecutive_failures": 0, "sleep_seconds": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_backoff(payload: dict) -> None:
    _backoff_state_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _compute_sleep(interval_seconds: int, *, failed: bool) -> int:
    policy = _loop_policy()
    if not policy.get("backoff_enabled", True):
        return interval_seconds
    state = _load_backoff()
    base = int(policy.get("backoff_base_seconds", 300))
    max_sleep = int(policy.get("backoff_max_seconds", 7200))
    multiplier = int(policy.get("backoff_multiplier", 2))
    if failed:
        failures = int(state.get("consecutive_failures", 0)) + 1
        sleep_seconds = min(max_sleep, base * (multiplier ** min(failures - 1, 4)))
        _save_backoff({"consecutive_failures": failures, "sleep_seconds": sleep_seconds})
        return max(interval_seconds, sleep_seconds)
    if policy.get("reset_backoff_on_success", True):
        _save_backoff({"consecutive_failures": 0, "sleep_seconds": 0})
    return interval_seconds


def run_loop(
    *,
    interval_seconds: int,
    max_cycles: int = 0,
    skip_validation: bool = False,
) -> list[CycleState]:
    if _background_mode() and not fully_autonomous():
        skip_validation = True
    pipeline = SDLCPipeline()
    completed: list[CycleState] = []
    count = 0
    while True:
        count += 1
        cycle = pipeline.run_cycle(skip_validation=skip_validation)
        completed.append(cycle)
        log(
            f"[cycle {cycle.cycle_id}] status={cycle.status} gap={cycle.active_gap_id} "
            f"artifacts=artifacts/cycle-{cycle.cycle_id:04d}/"
        )
        print(
            f"[cycle {cycle.cycle_id}] status={cycle.status} "
            f"gap={cycle.active_gap_id} artifacts=artifacts/cycle-{cycle.cycle_id:04d}/"
        )
        if cycle.status != "completed":
            print(f"  errors: {'; '.join(cycle.errors)}")
        elif cycle.metadata.get("merge_succeeded"):
            print(f"  merged: {cycle.metadata.get('merge_commit_sha', '—')} pushed={cycle.metadata.get('merge_pushed')}")
        email_result = maybe_send_weekly_report()
        if email_result.get("sent"):
            print(f"  summary email sent to {email_result.get('recipient')}")
        elif email_result.get("error"):
            print(f"  summary email error: {email_result['error']}")
        if max_cycles and count >= max_cycles:
            break
        sleep_for = _compute_sleep(interval_seconds, failed=cycle.status != "completed")
        print(f"  sleeping {sleep_for}s before next cycle…")
        time.sleep(sleep_for)
    return completed
