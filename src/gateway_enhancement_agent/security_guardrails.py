"""Pre-apply security guardrails for autonomous patches."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from gateway_enhancement_agent.config import load_json


@dataclass
class GuardrailResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_review_verdict(text: str) -> str | None:
    """Return APPROVE, BLOCKER, or None when no explicit verdict line is present."""
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip().strip("*").strip()
        upper = stripped.upper()
        if not upper.startswith("VERDICT"):
            continue
        value = stripped.split(":", 1)[1].strip().strip("*").strip().upper() if ":" in stripped else ""
        if "BLOCKER" in value:
            return "BLOCKER"
        if "APPROVE" in value:
            return "APPROVE"
    return None


class SecurityGuardrails:
    def __init__(self) -> None:
        raw = load_json("security_guardrails.json")
        self.blocked_path_patterns = list(raw.get("blocked_path_patterns", []))
        self.blocked_content_patterns = [
            re.compile(p, re.IGNORECASE) for p in raw.get("blocked_content_patterns", [])
        ]
        self.max_file_bytes = int(raw.get("max_file_bytes", 524288))
        self.require_review_for_paths = list(raw.get("require_review_for_paths", []))
        lenses = load_json("role_lenses.json")
        self.mandatory_review_ids = {
            lens["id"]
            for lens in lenses.get("lenses", [])
            if lens.get("mandatory", False)
        }

    def check_blocks(self, blocks: dict[str, str]) -> GuardrailResult:
        violations: list[str] = []
        warnings: list[str] = []
        for rel, content in blocks.items():
            lower = rel.lower()
            for pattern in self.blocked_path_patterns:
                if pattern.lower() in lower:
                    violations.append(f"Blocked path pattern `{pattern}` in `{rel}`")
            if len(content.encode("utf-8")) > self.max_file_bytes:
                violations.append(f"File `{rel}` exceeds max size ({self.max_file_bytes} bytes)")
            for regex in self.blocked_content_patterns:
                if regex.search(content):
                    violations.append(f"Blocked secret pattern in `{rel}`")
            if any(rel.endswith(p) or rel == p for p in self.require_review_for_paths):
                warnings.append(f"Privileged path modified: `{rel}` — role-lens review required")
        return GuardrailResult(passed=not violations, violations=violations, warnings=warnings)

    def check_reviews(self, reviews: dict[str, str]) -> GuardrailResult:
        violations: list[str] = []
        warnings: list[str] = []
        for worker_id, text in reviews.items():
            verdict = parse_review_verdict(text)
            if verdict == "BLOCKER":
                if worker_id in self.mandatory_review_ids:
                    violations.append(f"Review worker `{worker_id}` verdict BLOCKER")
                else:
                    warnings.append(f"Review worker `{worker_id}` verdict BLOCKER (non-mandatory, advisory)")
            elif verdict is None and "BLOCKER" in text.upper():
                warnings.append(
                    f"Review `{worker_id}` mentions BLOCKER without explicit Verdict line (ignored)"
                )
        return GuardrailResult(passed=not violations, violations=violations, warnings=warnings)
