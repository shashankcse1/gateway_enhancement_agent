from __future__ import annotations

from gateway_enhancement_agent.prompt_budget import (
    build_context_from_paths,
    estimate_tokens,
    fit_messages_to_budget,
    prompt_token_budget,
    shrink_user_prompt,
    trim_to_token_budget,
)


def test_estimate_tokens() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_trim_to_token_budget() -> None:
    text = "x" * 1000
    out = trim_to_token_budget(text, 50)
    assert len(out) < len(text)
    assert "truncated" in out


def test_shrink_user_prompt_drops_context() -> None:
    user = "## Gap\ninfo\n\n## Repository context\nhuge\n\n## Required output\nfile"
    shrunk = shrink_user_prompt(user, level=1)
    assert "huge" not in shrunk
    assert "Minimal" in shrunk


def test_fit_messages_to_budget() -> None:
    system = "sys"
    user = "u" * 20000
    s, u, trimmed = fit_messages_to_budget(system=system, user=user, max_prompt_tokens=500)
    assert trimmed is True
    assert estimate_tokens(s) + estimate_tokens(u) <= 520


def test_prompt_token_budget() -> None:
    assert prompt_token_budget(num_ctx=8192, reserve_output_tokens=2048) == 5888


def test_build_context_from_paths_respects_budget() -> None:
    files = {
        "a.py": "line\n" * 500,
        "b.py": "other\n" * 500,
    }

    def read_file(rel: str) -> str:
        return files.get(rel, "")

    ctx = build_context_from_paths(
        ["a.py", "b.py"],
        read_file=read_file,
        max_files=2,
        max_file_chars=2000,
        max_total_tokens=300,
    )
    assert estimate_tokens(ctx) <= 350
