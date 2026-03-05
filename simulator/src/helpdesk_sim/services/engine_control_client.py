from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import httpx


VALID_ENGINE_STATES = {"offline", "waking", "pc_online", "ready"}


def normalize_engine_state(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        return "unknown"

    candidates = [
        payload.get("state"),
        payload.get("engine_state"),
        payload.get("status"),
    ]
    for value in candidates:
        state = str(value or "").strip().lower()
        if state in VALID_ENGINE_STATES:
            return state

    if bool(payload.get("ready")):
        return "ready"
    if bool(payload.get("pc_online")):
        return "pc_online"
    if bool(payload.get("waking")):
        return "waking"
    if bool(payload.get("offline")):
        return "offline"
    return "unknown"


def is_engine_ready_state(state: str) -> bool:
    return str(state).strip().lower() == "ready"


def is_engine_online_state(state: str) -> bool:
    return str(state).strip().lower() in {"pc_online", "ready"}


@dataclass(slots=True)
class EngineControlClient:
    base_url: str
    api_key: str
    timeout_seconds: float = 8.0

    def is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip())

    def get_status(self) -> dict[str, object]:
        return self._request("GET", "/v1/engine/status")

    def wake(self) -> dict[str, object]:
        return self._request("POST", "/v1/engine/wake")

    def ensure_ready(self, timeout_seconds: int) -> dict[str, object]:
        payload = {"timeout_seconds": int(timeout_seconds)}
        return self._request("POST", "/v1/engine/ensure-ready", json=payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not self.is_configured():
            raise RuntimeError("engine controller is not configured")

        headers = {"Authorization": f"Bearer {self.api_key.strip()}"}
        with httpx.Client(base_url=self.base_url.strip(), timeout=self.timeout_seconds) as client:
            response = client.request(method=method, url=path, headers=headers, json=json)

        if response.status_code >= 400:
            detail = response.text.strip()
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("detail") or body.get("error") or detail)
            except Exception:
                pass
            raise RuntimeError(
                f"engine controller {method} {path} failed ({response.status_code}): {detail}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"engine controller {method} {path} returned invalid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"engine controller {method} {path} returned non-object JSON"
            )
        return data


@dataclass(slots=True)
class EngineReadinessCoordinator:
    engine_client: EngineControlClient | None
    auto_wake_enabled: bool = True
    auto_wake_timeout_seconds: int = 90
    success_cache_seconds: float = 8.0
    retry_cooldown_seconds: float = 2.0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _last_success_ts: float = field(default=0.0, init=False, repr=False)
    _last_failure_ts: float = field(default=0.0, init=False, repr=False)
    _last_failure_message: str = field(default="", init=False, repr=False)

    def controller_mode_enabled(self) -> bool:
        return bool(self.engine_client and self.engine_client.is_configured())

    def mark_wake_requested(self) -> None:
        # Clear cached "ready" state so the next preflight re-checks actual readiness.
        self._last_success_ts = 0.0

    def ensure_ready_for_llm(self) -> dict[str, object] | None:
        if not self.auto_wake_enabled or not self.controller_mode_enabled():
            return None

        now = time.monotonic()
        if now - self._last_success_ts < self.success_cache_seconds:
            return {"state": "ready", "cached": True}

        if now - self._last_failure_ts < self.retry_cooldown_seconds:
            raise RuntimeError(self._last_failure_message or "engine readiness check is cooling down")

        with self._lock:
            now = time.monotonic()
            if now - self._last_success_ts < self.success_cache_seconds:
                return {"state": "ready", "cached": True}
            if now - self._last_failure_ts < self.retry_cooldown_seconds:
                raise RuntimeError(
                    self._last_failure_message or "engine readiness check is cooling down"
                )

            assert self.engine_client is not None
            try:
                payload = self.engine_client.ensure_ready(
                    timeout_seconds=self.auto_wake_timeout_seconds
                )
            except Exception as exc:
                self._last_failure_ts = time.monotonic()
                self._last_failure_message = f"engine ensure-ready failed: {exc}"
                raise RuntimeError(self._last_failure_message) from exc

            state = normalize_engine_state(payload)
            ready = bool(payload.get("ready")) or is_engine_ready_state(state)
            if not ready:
                self._last_failure_ts = time.monotonic()
                self._last_failure_message = (
                    f"engine ensure-ready did not reach ready state (state={state})"
                )
                raise RuntimeError(self._last_failure_message)

            self._last_success_ts = time.monotonic()
            self._last_failure_ts = 0.0
            self._last_failure_message = ""
            return payload
