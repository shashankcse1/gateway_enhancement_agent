"""Continuous local competitor-check loop."""

from __future__ import annotations

import os
import time

from gateway_enhancement_agent.sdlc_pipeline import SDLCPipeline
from gateway_enhancement_agent.state_store import CycleState


def _background_mode() -> bool:
    return os.environ.get("AGENT_BACKGROUND_MODE", "").strip().lower() in {"1", "true", "yes"}


def run_loop(
    *,
    interval_seconds: int,
    max_cycles: int = 0,
    skip_validation: bool = False,
) -> list[CycleState]:
    if _background_mode():
        skip_validation = True
    pipeline = SDLCPipeline()
    completed: list[CycleState] = []
    count = 0
    while True:
        count += 1
        cycle = pipeline.run_cycle(skip_validation=skip_validation)
        completed.append(cycle)
        print(
            f"[cycle {cycle.cycle_id}] status={cycle.status} "
            f"gap={cycle.active_gap_id} artifacts=artifacts/cycle-{cycle.cycle_id:04d}/"
        )
        if cycle.status != "completed":
            print(f"  errors: {'; '.join(cycle.errors)}")
        if max_cycles and count >= max_cycles:
            break
        print(f"  sleeping {interval_seconds}s before next competitor check…")
        time.sleep(interval_seconds)
    return completed
