"""Run unit tests for the enhancement agent itself."""

from __future__ import annotations

from gateway_enhancement_agent.config import project_root
from gateway_enhancement_agent.validation_runner import ValidationRunner


class SelfTestRunner(ValidationRunner):
    def __init__(self) -> None:
        super().__init__(repo=project_root(), config_name="agent_self_tests.json")
