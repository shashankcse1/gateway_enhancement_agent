from __future__ import annotations

from gateway_enhancement_agent import progress_log


def test_verbose_stderr_foreground(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BACKGROUND_MODE", raising=False)
    monkeypatch.delenv("AGENT_QUIET", raising=False)
    monkeypatch.delenv("AGENT_VERBOSE", raising=False)
    assert progress_log.verbose_stderr() is True


def test_verbose_stderr_background_quiet_by_default(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BACKGROUND_MODE", "1")
    monkeypatch.delenv("AGENT_VERBOSE", raising=False)
    assert progress_log.verbose_stderr() is False


def test_verbose_stderr_background_with_flag(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BACKGROUND_MODE", "1")
    monkeypatch.setenv("AGENT_VERBOSE", "1")
    assert progress_log.verbose_stderr() is True


def test_log_writes_to_file(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_BACKGROUND_MODE", "1")
    monkeypatch.delenv("AGENT_VERBOSE", raising=False)
    progress_log.log("hello", phase="test")
    captured = capsys.readouterr()
    assert captured.err == ""
    log_path = tmp_path / ".runtime" / "agent.log"
    assert log_path.is_file()
    assert "hello" in log_path.read_text(encoding="utf-8")
