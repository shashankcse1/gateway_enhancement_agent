from __future__ import annotations

from gateway_enhancement_agent.file_blocks import extract_file_blocks, normalize_repo_path


def test_normalize_repo_path_rewrites_app_tests() -> None:
    assert normalize_repo_path("backend/app/tests/test_gateway.py") == "backend/tests/test_gateway.py"


def test_extract_file_blocks_normalizes_paths() -> None:
    text = "```file:backend/app/tests/test_x.py\nassert True\n```"
    blocks = extract_file_blocks(text)
    assert "backend/tests/test_x.py" in blocks
