from __future__ import annotations

from pathlib import Path

from gateway_enhancement_agent.delivery_config import (
    DeliveryConfig,
    filter_blocks_for_delivery,
    should_skip_review_stage,
    suggest_test_path,
)
from gateway_enhancement_agent.sdlc_validate import combined_summary, run_combined_validation
from gateway_enhancement_agent.security_guardrails import SecurityGuardrails
from gateway_enhancement_agent.validation_runner import GateResult, ValidationRunner


def test_delivery_config_full_mode(monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    from importlib import reload
    import gateway_enhancement_agent.delivery_config as mod

    reload(mod)
    cfg = mod.DeliveryConfig.from_env()
    assert cfg.full is True
    assert cfg.tests_first is False
    assert cfg.max_files_per_cycle == 6
    assert cfg.max_parallel_workers == 2
    assert "backend_contract" in cfg.prefer_implement_workers


def test_delivery_config_tests_first_mode(monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "tests_first")
    monkeypatch.setenv("DELIVERY_CONFIG", "delivery_tests_first.json")
    from importlib import reload
    import gateway_enhancement_agent.delivery_config as mod

    reload(mod)
    cfg = mod.DeliveryConfig.from_env()
    assert cfg.tests_first is True
    assert "backend/tests/" in cfg.allowed_write_prefixes
    assert cfg.max_files_per_cycle == 1


def test_suggest_test_path_from_route() -> None:
    path = suggest_test_path("inv-003", "GET /v1/vector_stores")
    assert path == "backend/tests/test_gateway_get_v1_vector_stores.py"
    path_only = suggest_test_path("inv-003", "/v1/vector_stores")
    assert path_only == "backend/tests/test_gateway_get_v1_vector_stores.py"


def test_filter_new_files_only_drops_existing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "tests_first")
    monkeypatch.setenv("DELIVERY_CONFIG", "delivery_tests_first.json")
    from importlib import reload
    import gateway_enhancement_agent.delivery_config as mod

    reload(mod)
    existing = tmp_path / "backend/tests/test_existing.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n", encoding="utf-8")
    blocks = {
        "backend/tests/test_existing.py": "new\n",
        "backend/tests/test_new_gap.py": "assert True\n",
    }
    filtered, dropped = mod.filter_blocks_for_delivery(blocks, tmp_path)
    assert "backend/tests/test_new_gap.py" in filtered
    assert not any("test_existing" in f for f in filtered)
    assert any("test_existing" in d for d in dropped)


def test_filter_blocks_frontend_forbidden_in_tests_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "tests_first")
    monkeypatch.setenv("DELIVERY_CONFIG", "delivery_tests_first.json")
    from importlib import reload
    import gateway_enhancement_agent.delivery_config as mod

    reload(mod)
    blocks = {"frontend/views/routing-gateway.html": "<section></section>\n"}
    filtered, dropped = mod.filter_blocks_for_delivery(blocks, tmp_path)
    assert filtered == {}
    assert dropped


def test_delivery_config_serial_default(monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    from importlib import reload
    import gateway_enhancement_agent.delivery_config as mod

    reload(mod)
    cfg = mod.DeliveryConfig.from_env()
    assert cfg.serial_llm is True
    assert cfg.max_parallel_workers == 2


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


def test_forbidden_overwrite_allows_patch_sized_content(tmp_path: Path) -> None:
    rel = "frontend/views/routing-gateway.html"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    original = "line\n" * 500
    path.write_text(original, encoding="utf-8")
    patched = original + "<button id=\"loadOpenAiVectorStoreDetail\">Load</button>\n"
    guard = SecurityGuardrails()
    result = guard.check_blocks({rel: patched}, repo_root=tmp_path)
    assert result.passed is True


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


def test_implement_workers_for_partial_with_test(mock_target_repo, monkeypatch) -> None:
    from gateway_enhancement_agent.delivery_config import DeliveryConfig
    from gateway_enhancement_agent.gap_models import GapItem

    monkeypatch.setenv("DELIVERY_MODE", "full")
    target = mock_target_repo / "backend/tests/test_gateway_get_v1_vector_stores.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("assert True\n", encoding="utf-8")
    gap = GapItem(
        gap_id="inv-003",
        title="GET /v1/vector_stores",
        source="api_inventory",
        priority=2,
        score=12,
        route="GET /v1/vector_stores",
        coverage="Partial",
    )
    workers = DeliveryConfig.from_env().implement_workers_for_gap(1, gap, mock_target_repo)
    assert workers == ["frontend_ui", "governance_docs"]


def test_should_skip_review_stage_governance_only() -> None:
    assert should_skip_review_stage(["backend/docs/governance/api-inventory-and-ui-map.md"]) is True
    assert should_skip_review_stage(
        [
            "backend/docs/governance/api-inventory-and-ui-map.md",
            "backend/docs/governance/ui-api-design-coverage-map.md",
        ]
    ) is True


def test_should_skip_review_stage_tests_only() -> None:
    assert should_skip_review_stage(["backend/tests/test_gateway_get_v1_vector_stores.py"]) is True
    assert should_skip_review_stage(["tests/test_foo.py"]) is True


def test_should_skip_review_stage_mixed_or_code() -> None:
    assert should_skip_review_stage([]) is False
    assert should_skip_review_stage(["backend/app/routers/gateway.py"]) is False
    assert should_skip_review_stage(
        [
            "backend/docs/governance/api-inventory-and-ui-map.md",
            "backend/app/routers/gateway.py",
        ]
    ) is False
