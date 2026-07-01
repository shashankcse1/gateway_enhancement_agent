"""Estimate and trim LLM prompts to stay within Ollama context limits."""

from __future__ import annotations

import re

_CONTEXT_SECTION = "## Repository context"
_DESIGN_SECTION = "## Design brief"


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English/code)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def trim_to_token_budget(text: str, max_tokens: int, *, marker: str = "... [truncated for context budget]") -> str:
    if max_tokens <= 0:
        return ""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(marker) - 1)
    return text[:keep].rstrip() + "\n" + marker


def prompt_token_budget(*, num_ctx: int, reserve_output_tokens: int, overhead_tokens: int = 256) -> int:
    return max(512, num_ctx - reserve_output_tokens - overhead_tokens)


def fit_messages_to_budget(
    *,
    system: str,
    user: str,
    max_prompt_tokens: int,
) -> tuple[str, str, bool]:
    """Trim user (then system) so combined estimate fits max_prompt_tokens."""
    sys_t = estimate_tokens(system)
    user_t = estimate_tokens(user)
    total = sys_t + user_t
    if total <= max_prompt_tokens:
        return system, user, False

    # Prefer shrinking repository context, then design brief, then hard trim user.
    shrunk_user = shrink_user_prompt(user, level=1)
    if sys_t + estimate_tokens(shrunk_user) <= max_prompt_tokens:
        return system, shrunk_user, True

    shrunk_user = shrink_user_prompt(user, level=2)
    if sys_t + estimate_tokens(shrunk_user) <= max_prompt_tokens:
        return system, shrunk_user, True

    user_budget = max(256, max_prompt_tokens - sys_t - 64)
    trimmed_user = trim_to_token_budget(shrunk_user, user_budget)
    if sys_t > max_prompt_tokens // 3:
        sys_budget = max(128, max_prompt_tokens // 4)
        system = trim_to_token_budget(system, sys_budget)
    return system, trimmed_user, True


def shrink_user_prompt(user: str, *, level: int) -> str:
    """Progressively drop prompt sections to save tokens."""
    if level <= 0:
        return user
    text = user
    if level >= 1 and _CONTEXT_SECTION in text:
        head, _ = text.split(_CONTEXT_SECTION, 1)
        text = head.rstrip() + f"\n\n{_CONTEXT_SECTION}\n_Minimal — follow template rules only._\n"
    if level >= 2 and _DESIGN_SECTION in text:
        parts = re.split(r"(?m)^## Design brief\s*$", text, maxsplit=1)
        if len(parts) == 2:
            before, after = parts
            rest = after.split("\n## ", 1)
            tail = "" if len(rest) == 1 else "\n## " + rest[1]
            text = before.rstrip() + f"\n\n{_DESIGN_SECTION}\n_Omitted for token budget._\n" + tail
    if level >= 3:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        text = "\n".join(lines[:40]) + "\n... [prompt minimized]\n"
    return text


def build_context_from_paths(
    paths: list[str],
    *,
    read_file,
    max_files: int,
    max_file_chars: int,
    max_total_tokens: int,
) -> str:
    """Build markdown context chunks without exceeding a total token budget."""
    chunks: list[str] = []
    used = 0
    for rel in paths[:max_files]:
        text = read_file(rel)
        if not text:
            continue
        if len(text) > max_file_chars:
            text = text[:max_file_chars] + "\n... [truncated]"
        block = f"### `{rel}`\n```\n{text}\n```"
        block_tokens = estimate_tokens(block)
        if used + block_tokens > max_total_tokens:
            remaining = max_total_tokens - used
            if remaining < 128:
                break
            block = trim_to_token_budget(block, remaining)
            chunks.append(block)
            break
        chunks.append(block)
        used += block_tokens
    if not chunks:
        return "_No context files found._"
    return "\n\n".join(chunks)
