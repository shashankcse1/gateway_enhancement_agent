"""Ollama client for implement/review/synthesizer agents (not web research)."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from gateway_enhancement_agent.config import load_json
from gateway_enhancement_agent.delivery_config import DeliveryConfig

_CHAT_LOCK = threading.Lock()


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    model: str
    fallback_models: list[str]
    timeout_seconds: int
    temperature: float
    num_ctx: int
    num_gpu: int
    num_thread: int
    auto_implement: bool
    max_context_files: int
    max_file_chars: int
    allowed_path_prefixes: list[str]

    @classmethod
    def from_env(cls) -> LLMConfig:
        raw = load_json("local_llm.json")
        enabled = os.environ.get("LOCAL_LLM_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
        auto = os.environ.get("LOCAL_LLM_AUTO_IMPLEMENT", "").strip().lower()
        auto_implement = raw.get("auto_implement", True)
        if auto in {"1", "true", "yes"}:
            auto_implement = True
        elif auto in {"0", "false", "no"}:
            auto_implement = False
        if not enabled:
            auto_implement = False
        return cls(
            provider=raw.get("provider", "ollama"),
            base_url=os.environ.get("LOCAL_LLM_BASE_URL", raw.get("base_url", "http://127.0.0.1:11434")).rstrip("/"),
            model=os.environ.get("LOCAL_LLM_MODEL", raw.get("model", "qwen2.5-coder:7b")),
            fallback_models=list(raw.get("fallback_models", [])),
            timeout_seconds=int(os.environ.get("LOCAL_LLM_TIMEOUT", raw.get("timeout_seconds", 600))),
            temperature=float(os.environ.get("LOCAL_LLM_TEMPERATURE", raw.get("temperature", 0.2))),
            num_ctx=int(os.environ.get("LOCAL_LLM_NUM_CTX", raw.get("num_ctx", 8192))),
            num_gpu=int(os.environ.get("LOCAL_LLM_NUM_GPU", raw.get("num_gpu", -1))),
            num_thread=int(os.environ.get("LOCAL_LLM_NUM_THREAD", raw.get("num_thread", 0))),
            auto_implement=auto_implement,
            max_context_files=int(raw.get("max_context_files", 6)),
            max_file_chars=int(raw.get("max_file_chars", 12000)),
            allowed_path_prefixes=list(raw.get("allowed_path_prefixes", ["backend/", "frontend/"])),
        )


@dataclass
class LLMHealth:
    reachable: bool
    provider: str
    base_url: str
    model: str
    model_available: bool
    available_models: list[str]
    error: str | None = None


class LocalLLMClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()

    def health(self) -> LLMHealth:
        models: list[str] = []
        try:
            payload = self._request("GET", "/api/tags", None)
            models = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
            model_available = self._pick_model(models) is not None
            return LLMHealth(
                reachable=True,
                provider=self.config.provider,
                base_url=self.config.base_url,
                model=self.config.model,
                model_available=model_available,
                available_models=models,
            )
        except Exception as exc:  # noqa: BLE001
            return LLMHealth(
                reachable=False,
                provider=self.config.provider,
                base_url=self.config.base_url,
                model=self.config.model,
                model_available=False,
                available_models=models,
                error=str(exc),
            )

    def chat(self, *, system: str, user: str) -> str:
        delivery = DeliveryConfig.from_env()
        if delivery.serial_llm:
            with _CHAT_LOCK:
                return self._chat_unlocked(system=system, user=user)
        return self._chat_unlocked(system=system, user=user)

    def _chat_unlocked(self, *, system: str, user: str) -> str:
        models = self._list_models()
        model = self._pick_model(models)
        if not model:
            raise RuntimeError(
                f"No local model available. Install one with: ollama pull {self.config.model}"
            )
        options: dict[str, Any] = {
            "temperature": self.config.temperature,
            "num_ctx": self.config.num_ctx,
        }
        if self.config.num_gpu != 0:
            options["num_gpu"] = self.config.num_gpu
        if self.config.num_thread > 0:
            options["num_thread"] = self.config.num_thread
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": options,
        }
        result = self._request("POST", "/api/chat", payload)
        message = result.get("message") or {}
        content = message.get("content", "")
        if not content.strip():
            raise RuntimeError("Local LLM returned empty response")
        return content

    def _list_models(self) -> list[str]:
        payload = self._request("GET", "/api/tags", None)
        return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]

    def _pick_model(self, available: list[str]) -> str | None:
        candidates = [self.config.model, *self.config.fallback_models]
        for name in candidates:
            if name in available:
                return name
            base = name.split(":")[0]
            for tag in available:
                if tag.split(":")[0] == base:
                    return tag
        return None

    def _request(self, method: str, path: str, body: dict | None) -> dict:
        url = f"{self.config.base_url}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Local LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Local LLM not reachable at {self.config.base_url}. "
                "Install Ollama (https://ollama.com) and run: ollama serve"
            ) from exc
