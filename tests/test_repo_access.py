from __future__ import annotations

from gateway_enhancement_agent.repo_access import read_repo_file


def test_read_repo_file_prefers_mirror(mock_target_repo, monkeypatch, tmp_path) -> None:
    mirror = tmp_path / "mirror"
    (mirror / "backend").mkdir(parents=True)
    (mirror / "backend" / "AGENTS.md").write_text("mirror agents", encoding="utf-8")
    monkeypatch.setenv("TARGET_REPO_MIRROR", str(mirror))
    assert read_repo_file("backend/AGENTS.md") == "mirror agents"
