"""Ollama client for implement/review/synthesizer agents (not web research)."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from gateway_enhancement_agent.config import load_json
from gateway_enhancement_agent.delivery_config import DeliveryConfig
from gateway_enhancement_agent.progress_log import log
from gateway_enhancement_agent.prompt_budget import (
    estimate_tokens,
    fit_messages_to_budget,
    prompt_token_budget,
    shrink_user_prompt,
)

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
    num_predict: int
    reserve_output_tokens: int
    max_prompt_tokens: int
    tests_first_max_context_files: int
    tests_first_max_file_chars: int
    max_design_brief_chars: int
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
            num_predict=int(os.environ.get("LOCAL_LLM_NUM_PREDICT", raw.get("num_predict", 1536))),
            reserve_output_tokens=int(
                os.environ.get("LOCAL_LLM_RESERVE_OUTPUT", raw.get("reserve_output_tokens", 2048))
            ),
            max_prompt_tokens=int(os.environ.get("LOCAL_LLM_MAX_PROMPT_TOKENS", raw.get("max_prompt_tokens", 0))),
            tests_first_max_context_files=int(raw.get("tests_first_max_context_files", 2)),
            tests_first_max_file_chars=int(raw.get("tests_first_max_file_chars", 3500)),
            max_design_brief_chars=int(raw.get("max_design_brief_chars", 800)),
            allowed_path_prefixes=list(raw.get("allowed_path_prefixes", ["backend/", "frontend/"])),
        )

    def effective_max_prompt_tokens(self) -> int:
        if self.max_prompt_tokens > 0:
            return self.max_prompt_tokens
        return prompt_token_budget(
            num_ctx=self.num_ctx,
            reserve_output_tokens=self.reserve_output_tokens,
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

    def chat(self, *, system: str, user: str, label: str | None = None) -> str:
        delivery = DeliveryConfig.from_env()
        if delivery.serial_llm:
            with _CHAT_LOCK:
                return self._chat_unlocked(system=system, user=user, label=label)
        return self._chat_unlocked(system=system, user=user, label=label)

    def _chat_unlocked(self, *, system: str, user: str, label: str | None = None) -> str:
        models = self._list_models()
        model = self._pick_model(models)
        if not model:
            raise RuntimeError(
                f"No local model available. Install one with: ollama pull {self.config.model}"
            )
        tag = label or "llm"
        budget = self.config.effective_max_prompt_tokens()
        system_fit, user_fit, trimmed = fit_messages_to_budget(
            system=system,
            user=user,
            max_prompt_tokens=budget,
        )
        if trimmed:
            est = estimate_tokens(system_fit) + estimate_tokens(user_fit)
            log(
                f"prompt trimmed to ~{est} tokens (budget={budget}, ctx={self.config.num_ctx})",
                phase="implement",
            )
        started = time.monotonic()
        last_error: str | None = None
        for attempt, shrink_level in enumerate((0, 1, 2)):
            attempt_user = user_fit if shrink_level == 0 else shrink_user_prompt(user_fit, level=shrink_level)
            attempt_system = system_fit
            if shrink_level > 0:
                attempt_system, attempt_user, _ = fit_messages_to_budget(
                    system=system_fit,
                    user=attempt_user,
                    max_prompt_tokens=budget,
                )
            content, done_reason = self._ollama_chat(
                model=model,
                system=attempt_system,
                user=attempt_user,
                label=tag,
                attempt=attempt,
            )
            if content.strip() and done_reason != "length":
                elapsed = time.monotonic() - started
                log(f"Ollama ✓ {tag} ({elapsed:.0f}s, {len(content)} chars)", phase="implement")
                return content
            last_error = "output truncated (token limit)" if done_reason == "length" else "empty response"
            log(f"Ollama retry {attempt + 1}/3 — {last_error}", phase="implement")
        raise RuntimeError(f"Local LLM failed after token-limit retries: {last_error}")

    def _ollama_chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        label: str,
        attempt: int,
    ) -> tuple[str, str | None]:
        log(
            f"Ollama → {label} (model={model}, attempt={attempt + 1}, "
            f"~{estimate_tokens(system) + estimate_tokens(user)} prompt tokens)",
            phase="implement",
        )
        options: dict[str, Any] = {
            "temperature": self.config.temperature,
            "num_ctx": self.config.num_ctx,
            "num_predict": self.config.num_predict,
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
        done_reason = result.get("done_reason")
        return content, done_reason

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
