from __future__ import annotations

from pathlib import Path

from gateway_enhancement_agent.delivery_config import DeliveryConfig, filter_blocks_for_delivery, suggest_test_path
from gateway_enhancement_agent.sdlc_validate import combined_summary, run_combined_validation
from gateway_enhancement_agent.security_guardrails import SecurityGuardrails
from gateway_enhancement_agent.validation_runner import GateResult, ValidationRunner


def test_delivery_config_tests_first_mode() -> None:
    cfg = DeliveryConfig.from_env()
    assert cfg.tests_first is True
    assert "backend/tests/" in cfg.allowed_write_prefixes
    assert cfg.max_files_per_cycle == 1


def test_suggest_test_path_from_route() -> None:
    path = suggest_test_path("inv-003", "GET /v1/vector_stores")
    assert path == "backend/tests/test_gateway_get_v1_vector_stores.py"


def test_filter_new_files_only_drops_existing(tmp_path) -> None:
    existing = tmp_path / "backend/tests/test_existing.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n", encoding="utf-8")
    blocks = {
        "backend/tests/test_existing.py": "new\n",
        "backend/tests/test_new_gap.py": "assert True\n",
    }
    filtered, dropped = filter_blocks_for_delivery(blocks, tmp_path)
    assert "backend/tests/test_new_gap.py" in filtered
    assert not any("test_existing" in f for f in filtered)
    assert any("test_existing" in d for d in dropped)


def test_filter_blocks_frontend_forbidden_in_tests_first(tmp_path) -> None:
    blocks = {"frontend/views/routing-gateway.html": "<section></section>\n"}
    filtered, dropped = filter_blocks_for_delivery(blocks, tmp_path)
    assert filtered == {}
    assert dropped


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


def test_combined_validation_skips_self_tests_in_background_for_target_tests(monkeypatch, mock_target_repo) -> None:
    monkeypatch.setenv("AGENT_BACKGROUND_MODE", "1")
    calls: list[str] = []

    class _Runner:
        def run_all(self) -> list[GateResult]:
            calls.append("ran")
            return [GateResult("agent_unit_tests", "Agent tests", True, False, 1, "", "fail")]

    monkeypatch.setattr("gateway_enhancement_agent.sdlc_validate.SelfTestRunner", _Runner)
    monkeypatch.setattr(
        "gateway_enhancement_agent.sdlc_validate.ValidationRunner.run_all",
        lambda self, changed_files=None: [],
    )
    combined = run_combined_validation(changed_files=["backend/tests/test_gateway_new.py"])
    assert calls == []
    assert combined.self_results == []
    assert combined_summary(combined)["self_test_passed"] is True


def test_scoped_pytest_strips_backend_prefix(mock_target_repo) -> None:
    runner = ValidationRunner(mock_target_repo)
    cmd = runner._resolve_command(
        ["python3", "-m", "pytest", "-q", "tests/test_gateway_inference.py"],
        cwd=mock_target_repo / "backend",
        changed_files=["backend/tests/test_gateway_vector_stores.py"],
    )
    assert "tests/test_gateway_vector_stores.py" in cmd
    assert "backend/tests/" not in " ".join(cmd)
    assert "tests/test_gateway_inference.py" not in cmd
