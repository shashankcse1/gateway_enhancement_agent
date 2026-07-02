"""Apply Aider-style SEARCH/REPLACE edits (diff format) for large existing files.

Market reference: Aider editblock format — efficient for local LLMs because the model
returns only changed hunks, not whole files. See https://aider.chat/docs/more/edit-formats.html
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from gateway_enhancement_agent.path_utils import allowed_repo_path, normalize_repo_path

SEARCH_MARKER = "<<<<<<< SEARCH"
DIVIDER_MARKER = "======="
REPLACE_MARKER = ">>>>>>> REPLACE"

# path line, optional language, then SEARCH/REPLACE inside fence
_AIDER_BLOCK_RE = re.compile(
    r"(?:^|\n)(?P<path>(?:backend|frontend)/[^\n`]+)\n"
    r"```(?:\w+)?\s*\n"
    r"(?P<body>.*?<<<<<<< SEARCH.*?>>>>>>> REPLACE.*?)\n"
    r"```",
    re.DOTALL | re.MULTILINE,
)

_PATCH_FENCE_RE = re.compile(
    r"```patch:([^\n`]+)\n([\s\S]*?)```",
    re.IGNORECASE,
)

_MD_PATH_FENCE_RE = re.compile(
    r"(?:^|\n)#{1,4}\s*`((?:backend|frontend)/[^`]+)`\s*\n"
    r"```[\w]*\s*\n"
    r"(?P<body>.*?>>>>>>> REPLACE\s*)\n"
    r"```",
    re.DOTALL,
)

_HUNK_RE = re.compile(
    rf"{re.escape(SEARCH_MARKER)}\s*\n(.*?)\n{re.escape(DIVIDER_MARKER)}\s*\n(.*?)\n{re.escape(REPLACE_MARKER)}",
    re.DOTALL,
)


@dataclass
class SearchReplaceHunk:
    path: str
    search: str
    replace: str


@dataclass
class PatchApplyResult:
    written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    preview: dict[str, str] = field(default_factory=dict)


def extract_search_replace_hunks(text: str) -> list[SearchReplaceHunk]:
    """Parse SEARCH/REPLACE hunks from LLM output (Aider diff + patch fences)."""
    hunks: list[SearchReplaceHunk] = []
    seen: set[tuple[str, str, str]] = set()

    for match in _PATCH_FENCE_RE.finditer(text):
        rel = normalize_repo_path(match.group(1).strip())
        hunks.extend(_hunks_from_body(rel, match.group(2), seen))

    for match in _AIDER_BLOCK_RE.finditer(text):
        rel = normalize_repo_path(match.group("path").strip())
        hunks.extend(_hunks_from_body(rel, match.group("body"), seen))

    for match in _MD_PATH_FENCE_RE.finditer(text):
        rel = normalize_repo_path(match.group(1).strip())
        hunks.extend(_hunks_from_body(rel, match.group("body"), seen))

    # Bare hunks with preceding path comment: `# file: backend/...`
    for path_match in re.finditer(r"(?:^|\n)#+\s*file:\s*([^\n]+)", text, re.IGNORECASE):
        rel = normalize_repo_path(path_match.group(1).strip())
        tail = text[path_match.end() :]
        hunks.extend(_hunks_from_body(rel, tail, seen, limit=8))

    return hunks


_INVALID_HUNK_MARKERS = (
    "... [truncated]",
    "lines omitted]",
    "...[truncated",
)


_UI_PATH_PREFIXES = ("frontend/",)


def _is_ui_path(rel: str) -> bool:
    return any(rel.startswith(p) for p in _UI_PATH_PREFIXES)


def _hunk_text_valid(text: str, *, max_lines: int = 40, min_lines: int = 0) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _INVALID_HUNK_MARKERS):
        return False
    line_count = len(_normalize_lines(text))
    if line_count > max_lines:
        return False
    if min_lines and line_count < min_lines and text.strip():
        return False
    return True


def _hunks_from_body(
    rel: str,
    body: str,
    seen: set[tuple[str, str, str]],
    *,
    limit: int = 32,
) -> list[SearchReplaceHunk]:
    found: list[SearchReplaceHunk] = []
    for match in _HUNK_RE.finditer(body):
        if len(found) >= limit:
            break
        search = match.group(1)
        replace = match.group(2)
        if _is_ui_path(rel):
            # UI hunks: tight SEARCH (5-15 lines); append-mode may use 1-4 line anchors.
            search_ok = _hunk_text_valid(search, max_lines=15, min_lines=0 if not search.strip() else 1)
            if search.strip() and len(_normalize_lines(search)) > 15:
                search_ok = False
            elif search.strip() and 1 <= len(_normalize_lines(search)) < 5:
                # Allow short anchors only when REPLACE clearly appends (longer than SEARCH).
                search_ok = len(_normalize_lines(replace)) > len(_normalize_lines(search))
            replace_ok = _hunk_text_valid(replace, max_lines=60)
        else:
            search_ok = _hunk_text_valid(search)
            replace_ok = _hunk_text_valid(replace, max_lines=80)
        if not search_ok or not replace_ok:
            continue
        key = (rel, search, replace)
        if key in seen:
            continue
        seen.add(key)
        found.append(SearchReplaceHunk(path=rel, search=search, replace=replace))
    return found


def _normalize_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return normalized.split("\n") if normalized else []


def _line_equiv(a: str, b: str) -> bool:
    if a.rstrip() == b.rstrip():
        return True
    # Indentation drift (tabs vs spaces) when body text matches.
    return a.lstrip() == b.lstrip() and bool(a.lstrip())


def _lines_match(a: list[str], b: list[str]) -> bool:
    if len(a) != len(b):
        return False
    return all(_line_equiv(x, y) for x, y in zip(a, b))


def _normalize_markdown_row(line: str) -> str:
    if "|" not in line:
        return line.strip()
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return "|".join(cells)


def _route_from_table_row(line: str) -> str | None:
    match = re.search(r"`([^`]+)`", line)
    return match.group(1).strip() if match else None


def _table_row_match_index(content_lines: list[str], search_lines: list[str]) -> int | None:
    if len(search_lines) != 1 or "|" not in search_lines[0]:
        return None
    norm_search = _normalize_markdown_row(search_lines[0])
    route = _route_from_table_row(search_lines[0])
    method = norm_search.split("|", 1)[0].upper() if norm_search else ""
    for i, line in enumerate(content_lines):
        if "|" not in line:
            continue
        norm_line = _normalize_markdown_row(line)
        if norm_line == norm_search:
            return i
        if route and route in line and method and line.lstrip().upper().startswith(f"| {method}"):
            return i
    return None


def find_hunk_location(content: str, search: str, *, threshold: float = 0.92) -> int | None:
    """Return start line index for search block, or None."""
    content_lines = _normalize_lines(content)
    search_lines = _normalize_lines(search)
    if not search_lines:
        return 0 if not content_lines else None

    # Exact contiguous match (first occurrence)
    for i in range(len(content_lines) - len(search_lines) + 1):
        chunk = content_lines[i : i + len(search_lines)]
        if _lines_match(chunk, search_lines):
            return i

    table_index = _table_row_match_index(content_lines, search_lines)
    if table_index is not None:
        return table_index

    # Fuzzy sliding window (Aider-style tolerance for minor whitespace drift)
    best_ratio = 0.0
    best_index: int | None = None
    window = len(search_lines)
    if window == 0:
        return 0
    for i in range(max(1, len(content_lines) - window + 1)):
        chunk = content_lines[i : i + window]
        ratio = SequenceMatcher(
            None,
            [l.rstrip().expandtabs() for l in search_lines],
            [l.rstrip().expandtabs() for l in chunk],
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = i
    if best_index is not None and best_ratio >= threshold:
        return best_index
    return None


def apply_hunk_to_content(content: str, search: str, replace: str) -> tuple[str | None, str | None]:
    """Apply one hunk; return (new_content, error)."""
    search_lines = _normalize_lines(search)
    replace_lines = _normalize_lines(replace)

    # New file: empty SEARCH
    if search == "" or (len(search_lines) == 1 and search_lines[0] == ""):
        new_text = replace if replace.endswith("\n") else replace + "\n"
        return new_text, None

    if not content and search_lines:
        return None, "SEARCH block is non-empty but target file is empty"

    start = find_hunk_location(content, search)
    if start is None:
        preview = search_lines[:3]
        return None, f"SEARCH block not found (starts with: {preview!r})"

    content_lines = _normalize_lines(content)
    end = start + len(search_lines)
    merged = content_lines[:start] + replace_lines + content_lines[end:]
    new_content = "\n".join(merged)
    if content.endswith("\n") or not content:
        if not new_content.endswith("\n"):
            new_content += "\n"
    return new_content, None


def preview_patches(
    repo: Path,
    hunks: list[SearchReplaceHunk],
    *,
    initial: dict[str, str] | None = None,
) -> PatchApplyResult:
    """Dry-run hunks; return resulting file contents in preview."""
    result = PatchApplyResult()
    working: dict[str, str] = dict(initial or {})

    for hunk in hunks:
        rel = normalize_repo_path(hunk.path)
        if rel in working:
            current = working[rel]
        else:
            dest = repo / rel
            current = dest.read_text(encoding="utf-8") if dest.is_file() else ""
        new_content, err = apply_hunk_to_content(current, hunk.search, hunk.replace)
        if err:
            result.errors.append(f"{rel}: {err}")
            continue
        working[rel] = new_content or ""
        if rel not in result.written:
            result.written.append(rel)

    result.preview = working
    return result


def apply_search_replace_hunks(
    repo: Path,
    hunks: list[SearchReplaceHunk],
    *,
    allowed_prefixes: list[str],
) -> PatchApplyResult:
    """Apply hunks to disk in order (multiple hunks per file are chained)."""
    preview = preview_patches(repo, hunks)
    result = PatchApplyResult(errors=list(preview.errors))

    for rel, content in preview.preview.items():
        if not allowed_repo_path(rel, allowed_prefixes):
            result.errors.append(f"{rel}: path not allowed")
            continue
        dest = (repo / rel).resolve()
        if not str(dest).startswith(str(repo.resolve())):
            result.errors.append(f"{rel}: path escapes repo")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        result.written.append(rel)

    return result


def exact_anchor_lines(
    content: str,
    *,
    anchors: list[str],
    window: int = 8,
) -> str | None:
    """Return exact consecutive lines around the first anchor match (safe SEARCH template)."""
    if not content or not anchors:
        return None
    lines = content.splitlines()
    lowered = [ln.lower() for ln in lines]
    anchor_idx: int | None = None
    for anchor in anchors:
        a = anchor.lower()
        for i, ln in enumerate(lowered):
            if a in ln:
                anchor_idx = i
                break
        if anchor_idx is not None:
            break
    if anchor_idx is None:
        return None
    half = max(2, window // 2)
    start = max(0, anchor_idx - half)
    end = min(len(lines), anchor_idx + half + 1)
    return "\n".join(lines[start:end])


def governance_row_snippet(content: str, route_path: str, *, context_rows: int = 2) -> str:
    """Extract the inventory table row (plus neighbors) for a route path."""
    if not content or not route_path:
        return content[:1200] if content else ""
    lines = content.splitlines()
    norm_path = route_path.strip().rstrip("/")
    hit: int | None = None
    for i, line in enumerate(lines):
        if norm_path in line and "|" in line:
            hit = i
            break
    if hit is None:
        return content[:1200]
    start = max(0, hit - context_rows)
    end = min(len(lines), hit + context_rows + 1)
    return "\n".join(lines[start:end])


def ui_scoped_snippet(
    content: str,
    *,
    anchors: list[str],
    context_lines: int = 12,
    max_chars: int = 2200,
) -> str:
    """Return a single tight UI anchor window — never whole hub/tab blocks."""
    if not content:
        return ""
    lines = content.splitlines()
    lowered = [ln.lower() for ln in lines]
    indices: list[int] = []
    for anchor in anchors:
        a = anchor.lower()
        for i, ln in enumerate(lowered):
            if a in ln:
                indices.append(i)
                break
    if not indices:
        return scoped_file_snippet(content, anchors=anchors, context_lines=context_lines, max_chars=max_chars)

    anchor_idx = indices[0]
    half = max(4, context_lines // 2)
    start = max(0, anchor_idx - half)
    end = min(len(lines), anchor_idx + half + 1)
    snippet = "\n".join(lines[start:end])
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "\n... [truncated for context budget]"
    return snippet


def scoped_file_snippet(
    content: str,
    *,
    anchors: list[str],
    context_lines: int = 60,
    max_chars: int = 8000,
) -> str:
    """Return a bounded window around route/handler anchors for patch prompts."""
    if not content:
        return ""
    lines = content.splitlines()
    indices: list[int] = []
    lowered = [ln.lower() for ln in lines]
    for anchor in anchors:
        a = anchor.lower()
        for i, ln in enumerate(lowered):
            if a in ln:
                indices.append(i)
    if not indices:
        head = "\n".join(lines[: min(len(lines), context_lines)])
        return head + ("\n... [truncated]" if len(lines) > context_lines else "")

    start = max(0, min(indices) - context_lines // 2)
    end = min(len(lines), max(indices) + context_lines // 2 + 1)
    snippet = "\n".join(lines[start:end])
    if start > 0:
        snippet = f"... [{start} lines omitted]\n" + snippet
    if end < len(lines):
        snippet += f"\n... [{len(lines) - end} lines omitted]"
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "\n... [truncated for context budget]"
    return snippet
