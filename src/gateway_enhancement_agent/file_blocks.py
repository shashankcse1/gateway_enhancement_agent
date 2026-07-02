"""Parse and apply LLM file blocks and SEARCH/REPLACE patches."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from gateway_enhancement_agent.delivery_config import DeliveryConfig
from gateway_enhancement_agent.path_utils import allowed_repo_path, normalize_repo_path
from gateway_enhancement_agent.patch_blocks import (
    apply_search_replace_hunks,
    extract_search_replace_hunks,
    preview_patches,
)


FILE_BLOCK_RE = re.compile(
    r"```(?:(?:\w+):)?(?:file:?|path:?)\s*([^\n`]+)\n([\s\S]*?)```",
    re.IGNORECASE,
)


@dataclass
class ApplyEditsResult:
    written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    preview_blocks: dict[str, str] = field(default_factory=dict)


def extract_file_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in FILE_BLOCK_RE.finditer(text):
        rel = normalize_repo_path(match.group(1).strip())
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
    return apply_llm_edits(repo, text, allowed_prefixes=allowed_prefixes).written


def apply_llm_edits(
    repo: Path,
    text: str,
    *,
    allowed_prefixes: list[str],
) -> ApplyEditsResult:
    """Apply patch hunks first, then full-file blocks for small/new paths only."""
    delivery = DeliveryConfig.from_env()
    result = ApplyEditsResult()
    hunks = extract_search_replace_hunks(text)
    file_blocks = extract_file_blocks(text)

    # Reject full-file blocks targeting large/forbidden paths when patches are required.
    for rel, _content in list(file_blocks.items()):
        if delivery.requires_patch_mode(rel, repo):
            result.errors.append(
                f"{rel}: full-file block rejected — use SEARCH/REPLACE patches for large or forbidden paths"
            )
            del file_blocks[rel]

    preview = preview_patches(repo, hunks)
    result.errors.extend(preview.errors)
    merged_preview = dict(preview.preview)

    for rel, content in file_blocks.items():
        if rel in merged_preview:
            result.errors.append(f"{rel}: both patch and file block provided — file block skipped")
            continue
        merged_preview[rel] = content

    result.preview_blocks = merged_preview

    if preview.errors and not preview.preview:
        # If patches failed entirely, still allow pure new-file blocks.
        if not file_blocks:
            return result

    patch_written = apply_search_replace_hunks(repo, hunks, allowed_prefixes=allowed_prefixes).written
    result.written.extend(patch_written)

    for rel, content in sorted(file_blocks.items()):
        if not _allowed_path(rel, allowed_prefixes):
            result.errors.append(f"{rel}: path not allowed")
            continue
        dest = (repo / rel).resolve()
        if not str(dest).startswith(str(repo.resolve())):
            result.errors.append(f"{rel}: path escapes repo")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        if rel not in result.written:
            result.written.append(rel)

    return result


def preview_llm_edits(repo: Path, text: str) -> dict[str, str]:
    """Dry-run patches + file blocks; return path → resulting content."""
    delivery = DeliveryConfig.from_env()
    hunks = extract_search_replace_hunks(text)
    file_blocks = extract_file_blocks(text)
    for rel in list(file_blocks.keys()):
        if delivery.requires_patch_mode(rel, repo):
            del file_blocks[rel]
    preview = preview_patches(repo, hunks)
    merged = dict(preview.preview)
    for rel, content in file_blocks.items():
        if rel not in merged:
            merged[rel] = content
    return merged


def write_content_blocks(
    repo: Path,
    blocks: dict[str, str],
    *,
    allowed_prefixes: list[str],
) -> list[str]:
    written: list[str] = []
    for rel, content in sorted(blocks.items()):
        if not _allowed_path(rel, allowed_prefixes):
            continue
        dest = (repo / rel).resolve()
        if not str(dest).startswith(str(repo.resolve())):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(rel)
    return written


def drop_unchanged_blocks(repo: Path, blocks: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Remove blocks whose content is identical to the file on disk."""
    changed: dict[str, str] = {}
    dropped: list[str] = []
    for rel, content in blocks.items():
        dest = repo / rel
        if dest.is_file():
            try:
                existing = dest.read_text(encoding="utf-8")
            except OSError:
                existing = ""
            if existing == content or existing.rstrip() == content.rstrip():
                dropped.append(f"{rel} (no-op — unchanged)")
                continue
        changed[rel] = content
    return changed, dropped


def merge_response_previews(repo: Path, responses: list[str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for response in responses:
        for rel, content in preview_llm_edits(repo, response).items():
            merged[rel] = content
    return merged


def _allowed_path(rel: str, allowed_prefixes: list[str]) -> bool:
    return allowed_repo_path(rel, allowed_prefixes)
