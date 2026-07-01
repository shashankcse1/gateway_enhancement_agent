from __future__ import annotations

from gateway_enhancement_agent.local_llm import LLMConfig


def make_llm_config(**overrides: object) -> LLMConfig:
    defaults = dict(
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
        max_file_chars=5000,
        num_predict=1536,
        reserve_output_tokens=1024,
        max_prompt_tokens=0,
        tests_first_max_context_files=2,
        tests_first_max_file_chars=3500,
        max_design_brief_chars=800,
        allowed_path_prefixes=["backend/"],
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)  # type: ignore[arg-type]
