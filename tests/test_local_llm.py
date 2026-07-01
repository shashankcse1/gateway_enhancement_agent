from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from gateway_enhancement_agent.code_implementer import CodeImplementer
from gateway_enhancement_agent.gap_analyzer import GapItem
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient


def test_local_llm_health_when_reachable() -> None:
    cfg = LLMConfig(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen2.5-coder:7b",
        fallback_models=[],
        timeout_seconds=5,
        temperature=0.2,
        num_ctx=4096,
        num_gpu=-1,
        num_thread=0,
        auto_implement=True,
        max_context_files=4,
        max_file_chars=1000,
        allowed_path_prefixes=["backend/"],
    )
    payload = json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]}).encode()

    class FakeResp:
        def read(self) -> bytes:
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        health = LocalLLMClient(cfg).health()
    assert health.reachable is True
    assert health.model_available is True


def test_code_implementer_applies_file_blocks(mock_target_repo, monkeypatch) -> None:
    gap = GapItem(
        gap_id="inv-001",
        title="DELETE /v1/responses/{id}",
        score=10,
        priority=1,
        source="inventory",
        route="DELETE /v1/responses/{id}",
        coverage="Gap",
        rationale="missing",
        competitor_ids=[],
        related_capabilities=[],
    )
    cfg = LLMConfig(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="test-model",
        fallback_models=[],
        timeout_seconds=5,
        temperature=0.2,
        num_ctx=4096,
        num_gpu=-1,
        num_thread=0,
        auto_implement=True,
        max_context_files=4,
        max_file_chars=5000,
        allowed_path_prefixes=["backend/"],
    )
    client = MagicMock()
    client.health.return_value = MagicMock(
        reachable=True,
        model_available=True,
        model="test-model",
        available_models=["test-model"],
        error=None,
    )
    client.chat.return_value = (
        "```file:backend/tests/test_delete_response.py\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n\n"
        "def test_delete_response():\n"
        "    assert TestClient(app).get('/gateway/routes').status_code in (200, 403)\n"
        "```"
    )
    artifact_dir = mock_target_repo / "artifacts" / "cycle-0001"
    artifact_dir.mkdir(parents=True)
    monkeypatch.setenv("PARALLEL_IMPLEMENT", "0")
    result = CodeImplementer(cfg, client).implement(
        gap,
        cycle_id=1,
        design_brief="# brief",
        artifact_dir=artifact_dir,
    )
    assert result.succeeded is True
    assert "backend/tests/test_delete_response.py" in result.files_written
    written = (mock_target_repo / "backend/tests/test_delete_response.py").read_text(encoding="utf-8")
    assert "delete_response" in written


def test_code_implementer_skips_when_auto_disabled(mock_target_repo) -> None:
    cfg = LLMConfig(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="test-model",
        fallback_models=[],
        timeout_seconds=5,
        temperature=0.2,
        num_ctx=4096,
        num_gpu=-1,
        num_thread=0,
        auto_implement=False,
        max_context_files=4,
        max_file_chars=5000,
        allowed_path_prefixes=["backend/"],
    )
    gap = GapItem(
        gap_id="x",
        title="t",
        score=1,
        priority=1,
        source="inventory",
        route=None,
        coverage="Gap",
        rationale="r",
        competitor_ids=[],
        related_capabilities=[],
    )
    result = CodeImplementer(cfg).implement(
        gap,
        cycle_id=1,
        design_brief="b",
        artifact_dir=mock_target_repo / "art",
    )
    assert result.attempted is False
    assert "AUTO_IMPLEMENT disabled" in (result.skipped_reason or "")
