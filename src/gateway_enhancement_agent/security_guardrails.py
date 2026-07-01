"""Pre-apply security guardrails for autonomous patches."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from gateway_enhancement_agent.config import load_json, target_repo
from gateway_enhancement_agent.delivery_config import DeliveryConfig
from gateway_enhancement_agent.file_blocks import normalize_repo_path

_MIN_LINES_DEFAULT: dict[str, int] = {
    "backend/app/routers/gateway.py": 500,
}


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

    def check_blocks(self, blocks: dict[str, str], *, repo_root=None) -> GuardrailResult:
        delivery = DeliveryConfig.from_env()
        repo = repo_root or target_repo()
        violations: list[str] = []
        warnings: list[str] = []
        min_lines_map = {**_MIN_LINES_DEFAULT, **delivery.min_lines_large_files}
        for raw_rel, content in blocks.items():
            rel = normalize_repo_path(raw_rel)
            lower = rel.lower()
            if delivery.is_forbidden_overwrite(rel) and (repo / rel).is_file():
                violations.append(
                    f"Full overwrite of `{rel}` is forbidden — add tests/docs/services instead"
                )
            for pattern in self.blocked_path_patterns:
                if pattern.lower() in lower:
                    violations.append(f"Blocked path pattern `{pattern}` in `{rel}`")
            if rel.startswith("backend/app/tests/"):
                violations.append(f"Tests must live under `backend/tests/`, not `{rel}`")
            if len(content.encode("utf-8")) > self.max_file_bytes:
                violations.append(f"File `{rel}` exceeds max size ({self.max_file_bytes} bytes)")
            for regex in self.blocked_content_patterns:
                if regex.search(content):
                    violations.append(f"Blocked secret pattern in `{rel}`")
            if rel.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    violations.append(f"Python syntax error in `{rel}`: {exc.msg}")
            min_lines = min_lines_map.get(rel)
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            if min_lines and line_count < min_lines:
                violations.append(
                    f"File `{rel}` has only {line_count} lines; likely truncated overwrite (min {min_lines})"
                )
            existing = repo / rel
            if existing.is_file() and rel.startswith("backend/docs/governance/"):
                try:
                    existing_lines = len(existing.read_text(encoding="utf-8").splitlines())
                except OSError:
                    existing_lines = 0
                if existing_lines >= 80 and line_count < int(existing_lines * 0.5):
                    violations.append(
                        f"File `{rel}` shrinks from {existing_lines} to {line_count} lines; "
                        "likely truncated governance overwrite"
                    )
            if any(rel.endswith(p) or rel == p for p in self.require_review_for_paths):
                warnings.append(f"Privileged path modified: `{rel}` — role-lens review required")
            violations.extend(self._check_test_imports(rel, content, Path(repo)))
        return GuardrailResult(passed=not violations, violations=violations, warnings=warnings)

    def _check_test_imports(self, rel: str, content: str, repo: Path) -> list[str]:
        if not rel.startswith("backend/tests/") or not rel.endswith(".py"):
            return []
        violations: list[str] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return violations
        backend_root = repo / "backend"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend."):
                        violations.append(f"Test `{rel}` must not import `{alias.name}` — use `app.*` only")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("backend."):
                    violations.append(f"Test `{rel}` must not import `{mod}` — use `app.*` only")
                if mod.startswith("app."):
                    if mod == "app.main":
                        continue
                    rel_path = mod.replace(".", "/")
                    candidates = [
                        backend_root / f"{rel_path}.py",
                        backend_root / rel_path / "__init__.py",
                    ]
                    if not any(p.is_file() for p in candidates):
                        violations.append(f"Test `{rel}` imports missing module `{mod}`")
        return violations

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
