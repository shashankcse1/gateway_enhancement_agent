"""Parse and apply LLM file blocks."""

from __future__ import annotations

import re
from pathlib import Path


FILE_BLOCK_RE = re.compile(
    r"```(?:(?:\w+):)?(?:file:?|path:?)\s*([^\n`]+)\n([\s\S]*?)```",
    re.IGNORECASE,
)


def extract_file_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in FILE_BLOCK_RE.finditer(text):
        rel = match.group(1).strip().lstrip("./")
        content = match.group(2)
        if not content.endswith("\n"):
            content += "\n"
        blocks[rel] = content
    return blocks


def apply_file_blocks(
    repo: Path,
    text: str,
    *,
    allowed_prefixes: list[str],
) -> list[str]:
    written: list[str] = []
    for rel, content in extract_file_blocks(text).items():
        if not _allowed_path(rel, allowed_prefixes):
            continue
        dest = (repo / rel).resolve()
        if not str(dest).startswith(str(repo.resolve())):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(rel)
    return written


def _allowed_path(rel: str, allowed_prefixes: list[str]) -> bool:
    if ".." in Path(rel).parts:
        return False
    return any(rel.startswith(prefix) for prefix in allowed_prefixes)
