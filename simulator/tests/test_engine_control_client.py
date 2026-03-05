from __future__ import annotations

import pytest

from helpdesk_sim.services.engine_control_client import EngineReadinessCoordinator


class _ReadyClient:
    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def is_configured() -> bool:
        return True

    def ensure_ready(self, timeout_seconds: int) -> dict[str, object]:
        self.calls += 1
        return {"state": "ready", "ready": True, "timeout_seconds": timeout_seconds}


class _FailingClient:
    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def is_configured() -> bool:
        return True

    def ensure_ready(self, timeout_seconds: int) -> dict[str, object]:
        self.calls += 1
        raise RuntimeError("engine offline")


def test_readiness_coordinator_caches_success_and_avoids_repeat_calls() -> None:
    client = _ReadyClient()
    coordinator = EngineReadinessCoordinator(
        engine_client=client,  # type: ignore[arg-type]
        auto_wake_enabled=True,
        auto_wake_timeout_seconds=30,
        success_cache_seconds=30.0,
        retry_cooldown_seconds=2.0,
    )

    first = coordinator.ensure_ready_for_llm()
    second = coordinator.ensure_ready_for_llm()

    assert first is not None
    assert first.get("ready") is True
    assert second is not None
    assert second.get("state") == "ready"
    assert client.calls == 1


def test_readiness_coordinator_applies_failure_cooldown() -> None:
    client = _FailingClient()
    coordinator = EngineReadinessCoordinator(
        engine_client=client,  # type: ignore[arg-type]
        auto_wake_enabled=True,
        auto_wake_timeout_seconds=30,
        success_cache_seconds=5.0,
        retry_cooldown_seconds=30.0,
    )

    with pytest.raises(RuntimeError, match="engine ensure-ready failed"):
        coordinator.ensure_ready_for_llm()

    with pytest.raises(RuntimeError, match="cooling down|engine ensure-ready failed"):
        coordinator.ensure_ready_for_llm()

    assert client.calls == 1
