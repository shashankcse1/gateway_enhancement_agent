"""Persist SDLC loop state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import artifacts_dir, runtime_dir


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class CycleState:
    cycle_id: int
    started_at: str
    phase: str
    target_repo: str
    status: str = "running"
    active_gap_id: str | None = None
    completed_phases: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class StateStore:
    def __init__(self) -> None:
        self.state_file = runtime_dir() / "state.json"
        self.artifacts_root = artifacts_dir()

    def load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"version": 1, "cycle_count": 0, "last_cycle": None, "history": []}
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def begin_cycle(self, target_repo: str) -> CycleState:
        state = self.load()
        cycle_id = int(state.get("cycle_count", 0)) + 1
        cycle = CycleState(
            cycle_id=cycle_id,
            started_at=_utc_now(),
            phase="discover",
            target_repo=target_repo,
        )
        state["cycle_count"] = cycle_id
        state["last_cycle"] = asdict(cycle)
        history = state.setdefault("history", [])
        history.append(asdict(cycle))
        state["history"] = history[-100:]
        self.save(state)
        return cycle

    def update_cycle(self, cycle: CycleState) -> None:
        state = self.load()
        state["last_cycle"] = asdict(cycle)
        if state.get("history"):
            state["history"][-1] = asdict(cycle)
        self.save(state)

    def cycle_dir(self, cycle_id: int) -> Path:
        path = self.artifacts_root / f"cycle-{cycle_id:04d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, cycle_id: int, name: str, content: str) -> Path:
        path = self.cycle_dir(cycle_id) / name
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, cycle_id: int, name: str, payload: Any) -> Path:
        path = self.cycle_dir(cycle_id) / name
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path
