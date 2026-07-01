from __future__ import annotations

from pathlib import Path

from gateway_enhancement_agent.delivery_config import DeliveryConfig
from gateway_enhancement_agent.security_guardrails import SecurityGuardrails
from gateway_enhancement_agent.validation_runner import ValidationRunner


def test_delivery_config_serial_default() -> None:
    cfg = DeliveryConfig.from_env()
    assert cfg.serial_llm is True
    assert cfg.max_parallel_workers == 1


def test_forbidden_overwrite_blocks_gateway_py(tmp_path: Path) -> None:
    gateway = tmp_path / "backend/app/routers/gateway.py"
    gateway.parent.mkdir(parents=True)
    gateway.write_text("x = 1\n" * 600, encoding="utf-8")
    guard = SecurityGuardrails()
    result = guard.check_blocks(
        {"backend/app/routers/gateway.py": "replacement\n"},
        repo_root=tmp_path,
    )
    assert result.passed is False
    assert any("forbidden" in v.lower() or "overwrite" in v.lower() for v in result.violations)


def test_scoped_pytest_command_uses_changed_tests_only(mock_target_repo) -> None:
    runner = ValidationRunner(mock_target_repo)
    cmd = runner._resolve_command(
        ["python3", "-m", "pytest", "-q", "tests/test_gateway_inference.py"],
        cwd=mock_target_repo / "backend",
        changed_files=["backend/tests/test_gateway_vector_stores.py"],
    )
    assert "backend/tests/test_gateway_vector_stores.py" in cmd
    assert "tests/test_gateway_inference.py" not in cmd
