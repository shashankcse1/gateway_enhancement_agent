from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _test_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(root / "config"))
    monkeypatch.setenv("AGENT_FULLY_AUTONOMOUS", "0")
    monkeypatch.setenv("WEEKLY_EMAIL_ENABLED", "0")
    monkeypatch.setenv("COMPETITOR_WEB_RESEARCH", "0")


@pytest.fixture
def mock_target_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    backend = tmp_path / "backend"
    docs = backend / "docs" / "governance"
    docs.mkdir(parents=True)
    (backend / "AGENTS.md").write_text("# Agents contract\n", encoding="utf-8")
    (backend / "app" / "routers").mkdir(parents=True)
    (backend / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (backend / "app" / "routers" / "gateway.py").write_text(
        '@router.get("/gateway/routes")\n@router.post("/v1/chat/completions")\n',
        encoding="utf-8",
    )
    (docs / "api-inventory-and-ui-map.md").write_text(
        """### `app/routers/gateway.py`

| Method | Route | UI Coverage | Notes |
| ------ | ----- | ----------- | ----- |
| GET | `/gateway/routes` | Full | ok |
| POST | `/v1/chat/completions` | Partial | missing UI |
| DELETE | `/v1/responses/{id}` | Gap | not wired |
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TARGET_REPO", str(tmp_path))
    return tmp_path
