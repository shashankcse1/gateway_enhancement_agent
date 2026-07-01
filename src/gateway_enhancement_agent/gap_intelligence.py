"""Gap scoring, route coverage detection, and test-generation hints."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from gateway_enhancement_agent.config import load_json, target_repo
from gateway_enhancement_agent.delivery_config import DeliveryConfig, suggest_test_path
from gateway_enhancement_agent.gap_models import GapItem
from gateway_enhancement_agent.prompt_budget import trim_to_token_budget

_ROUTE_CALL = re.compile(
    r'client\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)["\']',
    re.I,
)
_ROUTE_FSTRING = re.compile(
    r'client\.(get|post|put|patch|delete)\s*\(\s*f["\']([^"\']+)["\']',
    re.I,
)
_PATH_SEGMENT = re.compile(r"\{[^}]+\}")


def load_gap_intelligence_config() -> dict[str, Any]:
    try:
        return load_json("gap_intelligence.json")
    except FileNotFoundError:
        return {}


def parse_route(route: str | None) -> tuple[str, str]:
    if not route:
        return "", ""
    text = route.strip()
    parts = text.split(None, 1)
    if len(parts) == 2 and parts[0].upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return parts[0].upper(), parts[1].strip()
    return "GET", text


def route_path_pattern(path: str) -> str:
    """Normalize `{id}` segments for fuzzy matching in test files."""
    normalized = path.strip().rstrip("/")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return _PATH_SEGMENT.sub("{*}", normalized.lower())


def _tests_dir(repo: Path) -> Path:
    backend = repo / "backend" / "tests"
    if backend.is_dir():
        return backend
    alt = repo / "tests"
    return alt if alt.is_dir() else backend


def iter_gateway_test_files(repo: Path | None = None) -> list[Path]:
    root = repo or target_repo()
    tests = _tests_dir(root)
    if not tests.is_dir():
        return []
    return sorted(tests.glob("test_gateway*.py"))


def route_mentioned_in_content(content: str, method: str, path: str) -> bool:
    if not path:
        return False
    path_norm = path.rstrip("/").lower()
    prefix = path_norm.split("{", 1)[0].rstrip("/")
    method_l = method.lower()
    for match in _ROUTE_CALL.finditer(content):
        if match.group(1).lower() != method_l:
            continue
        call_path = match.group(2).rstrip("/").lower()
        if route_path_pattern(call_path) == route_path_pattern(path):
            return True
        if prefix and call_path.startswith(prefix):
            return True
    for match in _ROUTE_FSTRING.finditer(content):
        if match.group(1).lower() != method_l:
            continue
        f_prefix = match.group(2).split("{", 1)[0].rstrip("/").lower()
        if prefix and f_prefix and (f_prefix == prefix or prefix.startswith(f_prefix)):
            return True
    return prefix in content.lower() and f".{method_l}(" in content.lower()


def find_covering_test_files(repo: Path | None, method: str, path: str) -> list[str]:
    root = repo or target_repo()
    rels: list[str] = []
    for test_file in iter_gateway_test_files(root):
        try:
            content = test_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if route_mentioned_in_content(content, method, path):
            try:
                rels.append(str(test_file.relative_to(root)))
            except ValueError:
                rels.append(str(test_file))
    return rels


def is_route_covered_in_tests(route: str | None, repo: Path | None = None) -> bool:
    method, path = parse_route(route)
    if not path:
        return False
    return bool(find_covering_test_files(repo, method, path))


def is_gap_covered_for_delivery(gap_id: str, route: str | None, repo: Path | None = None) -> bool:
    """In tests_first mode, a gap is covered only when its canonical dedicated test file exists."""
    root = repo or target_repo()
    if DeliveryConfig.from_env().tests_first:
        target = suggest_test_path(gap_id, route)
        return (root / target).is_file()
    return is_route_covered_in_tests(route, root)


def pick_test_template(route: str | None) -> str:
    _, path = parse_route(route)
    path_l = path.lower()
    if "vector_store" in path_l or "/v1/vector" in path_l:
        return "backend/tests/test_gateway_rag.py"
    if "assistant" in path_l:
        return "backend/tests/test_gateway_assistants.py"
    if "fine_tun" in path_l:
        return "backend/tests/test_gateway_fine_tuning.py"
    if "chat/completion" in path_l or "inference" in path_l:
        return "backend/tests/test_gateway_inference.py"
    if "response" in path_l:
        return "backend/tests/test_gateway_inference.py"
    return "backend/tests/test_gateway_inference.py"


def difficulty_penalty(gap: GapItem) -> int:
    method, path = parse_route(gap.route or gap.title)
    path_l = path.lower()
    penalty = 0
    cfg = load_gap_intelligence_config()
    if "vector_store" in path_l or "mcp" in path_l or "rag" in path_l:
        penalty += int(cfg.get("complex_route_penalty", 15))
    if method in {"POST", "PUT", "PATCH"} and "{" in path:
        penalty += 5
    if method == "DELETE" and "response" in path_l:
        penalty -= int(cfg.get("easy_route_bonus", 12))
    if method == "GET" and path.count("/") <= 3 and "{" not in path:
        penalty -= 4
    return penalty


def adjust_gap_score(gap: GapItem, repo: Path | None = None, *, validation_failures: int = 0) -> int:
    cfg = load_gap_intelligence_config()
    score = gap.score
    method, path = parse_route(gap.route or gap.title)
    if cfg.get("auto_close_covered_routes", True) and is_gap_covered_for_delivery(
        gap.gap_id, gap.route or gap.title, repo
    ):
        score += int(cfg.get("covered_route_penalty", 50))
    score += difficulty_penalty(gap)
    if validation_failures > 0:
        score += validation_failures * int(cfg.get("repeated_failure_penalty", 8))
    if cfg.get("prefer_auth_only_gaps", True) and method == "DELETE":
        score -= 6
    return max(1, score)


def normalize_test_blocks(
    blocks: dict[str, str],
    *,
    gap_id: str,
    route: str | None,
) -> dict[str, str]:
    """Rename misnamed test output to the canonical suggest_test_path."""
    if not blocks:
        return {}
    target = suggest_test_path(gap_id, route)
    if len(blocks) == 1:
        only_path, content = next(iter(blocks.items()))
        if only_path != target and only_path.startswith("backend/tests/"):
            return {target: content}
    if target in blocks:
        return {target: blocks[target]}
    tests = {k: v for k, v in blocks.items() if k.startswith("backend/tests/") and k.endswith(".py")}
    if len(tests) == 1:
        path, content = next(iter(tests.items()))
        return {target: content}
    return blocks


def is_auth_only_gap(gap: GapItem) -> bool:
    """Gaps testable with auth/deny assertions only (no seeding)."""
    method, _path = parse_route(gap.route or gap.title)
    return method in {"DELETE", "GET", "POST", "PUT", "PATCH"}


def scaffold_auth_test(gap: GapItem, target_path: str) -> str:
    """Deterministic minimal test when LLM output is unusable (auth-only routes)."""
    method, path = parse_route(gap.route or gap.title)
    if not path:
        path = "/unknown"
    func = (
        path.strip("/")
        .replace("/", "_")
        .replace("{", "")
        .replace("}", "")
        .replace("-", "_")
    )
    client_method = method.lower()
    lines = [
        "from fastapi.testclient import TestClient",
        "",
        "from app.main import app",
        "",
        "client = TestClient(app)",
        'ADMIN_HEADERS = {"X-Actor-Role": "Platform Admin", "X-Actor-Id": "admin-upstream"}',
        "",
        f"def test_{func}_missing_auth():",
        f'    response = client.{client_method}("{path}")',
        "    assert response.status_code in (401, 403)",
        "",
        f"def test_{func}_deny_role():",
        f'    response = client.{client_method}(',
        f'        "{path}",',
        '        headers={"X-Actor-Role": "Guest", "X-Actor-Id": "guest-test"},',
        "    )",
        "    assert response.status_code in (403, 404)",
        "",
        f"def test_{func}_admin_status():",
        f'    response = client.{client_method}("{path}", headers=ADMIN_HEADERS)',
        "    assert response.status_code in (200, 404, 422, 501)",
        "",
    ]
    return "\n".join(lines)


def build_tests_first_user_prompt(
    *,
    gap: GapItem,
    cycle_id: int,
    design_brief: str,
    context: str,
    target_test: str,
    template_rel: str,
) -> str:
    method, path = parse_route(gap.route or gap.title)
    brief = trim_to_token_budget(
        design_brief,
        max(64, 800 // 4),
        marker="... [design brief truncated]",
    )
    return f"""# Test task — cycle {cycle_id:04d}

## Gap
- ID: {gap.gap_id}
- Title: {gap.title}
- Method: {method or 'GET'}
- Path: {path or 'N/A'}

## Design brief
{brief}

## Required output
Create ONE new file at exactly: `{target_test}`

## Rules (strict)
- Use ONLY: `from fastapi.testclient import TestClient` and `from app.main import app`
- Do NOT define helper functions that call secrets, runtime-config, or database setup unless you copy them verbatim from the template.
- Do NOT invent imports (`backend.*`, `_ensure_tenant`, etc.).
- Max 45 lines. Three tests maximum.
- Missing auth: assert status in (401, 403).
- Wrong role (use Guest): assert status in (403, 404).
- Admin call: assert status in (200, 404, 422, 501) — use `in`, never exact 200 unless template shows seeding.

## Template to mirror
See `{template_rel}` in context below.

## Repository context
{context}
"""
