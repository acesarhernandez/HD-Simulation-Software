from __future__ import annotations

import logging
import random
from datetime import timedelta

from helpdesk_sim.adapters.gateway import ZammadGateway
from helpdesk_sim.domain.models import IncidentInjection, SessionProfile, TicketRecord, TicketTier
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.generation_service import GenerationService
from helpdesk_sim.utils import utc_now

logger = logging.getLogger(__name__)


class SchedulerService:
    RUNTIME_PENDING_BATCHES_KEY = "_runtime_pending_batches"

    def __init__(
        self,
        repository: SimulatorRepository,
        generation_service: GenerationService,
        zammad_gateway: ZammadGateway,
        rng: random.Random | None = None,
    ) -> None:
        self.repository = repository
        self.generation_service = generation_service
        self.zammad_gateway = zammad_gateway
        self.rng = rng or random.Random()

    def tick(self) -> dict[str, int]:
        now = utc_now()
        sessions = self.repository.list_active_sessions()
        generated_count = 0

        for session in sessions:
            profile = SessionProfile.model_validate(session.config)
            session_config = dict(session.config)
            pending_batches = self._normalize_pending_batches(
                session_config.get(self.RUNTIME_PENDING_BATCHES_KEY, [])
            )

            if now >= session.ends_at:
                self.repository.complete_session(session.id)
                continue

            next_window = session.next_window_at
            window_index = session.window_index

            while now >= next_window and now < session.ends_at:
                if profile.business_hours_only and not self._is_business_hour(next_window):
                    next_window += timedelta(minutes=profile.cadence_minutes)
                    window_index += 1
                    continue

                if profile.trickle_mode:
                    self._queue_window_tickets(
                        pending_batches=pending_batches,
                        profile=profile,
                        window_index=window_index,
                    )
                else:
                    generated_count += self._generate_window_tickets(
                        session_id=session.id,
                        profile=profile,
                        window_index=window_index,
                    )

                next_window += timedelta(minutes=profile.cadence_minutes)
                window_index += 1

            if profile.trickle_mode:
                generated_count += self._emit_trickle_tickets(
                    session_id=session.id,
                    profile=profile,
                    pending_batches=pending_batches,
                )
                session_config[self.RUNTIME_PENDING_BATCHES_KEY] = pending_batches
                self.repository.update_session_config(session.id, session_config)
            elif self.RUNTIME_PENDING_BATCHES_KEY in session_config:
                session_config.pop(self.RUNTIME_PENDING_BATCHES_KEY, None)
                self.repository.update_session_config(session.id, session_config)

            self.repository.advance_session_window(
                session_id=session.id,
                next_window_at=next_window,
                window_index=window_index,
            )

        return {"sessions_checked": len(sessions), "tickets_generated": generated_count}

    def create_manual_ticket(
        self,
        session_id: str,
        forced_tier: TicketTier | None = None,
        forced_ticket_type: str | None = None,
        forced_department: str | None = None,
        forced_persona_id: str | None = None,
        forced_scenario_id: str | None = None,
        required_tags: list[str] | None = None,
    ) -> TicketRecord:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ValueError(f"session '{session_id}' does not exist")
        profile = SessionProfile.model_validate(session.config)
        return self._create_ticket(
            session_id=session_id,
            profile=profile,
            required_tags=required_tags,
            forced_tier=forced_tier,
            forced_ticket_type=forced_ticket_type,
            forced_department=forced_department,
            forced_persona_id=forced_persona_id,
            forced_scenario_id=forced_scenario_id,
        )

    def _generate_window_tickets(
        self,
        session_id: str,
        profile: SessionProfile,
        window_index: int,
    ) -> int:
        created = 0
        baseline = self.rng.randint(profile.tickets_per_window_min, profile.tickets_per_window_max)
        for _ in range(baseline):
            self._create_ticket(session_id=session_id, profile=profile)
            created += 1

        for injection in profile.incident_injections:
            if injection.at_window != window_index:
                continue
            for _ in range(injection.extra_tickets):
                self._create_ticket(
                    session_id=session_id,
                    profile=profile,
                    required_tags=injection.scenario_tags,
                )
                created += 1
            logger.info(
                "Applied incident injection '%s' for session %s at window %s",
                injection.name,
                session_id,
                window_index,
            )

        return created

    def _create_ticket(
        self,
        session_id: str,
        profile: SessionProfile,
        required_tags: list[str] | None = None,
        forced_tier: TicketTier | None = None,
        forced_ticket_type: str | None = None,
        forced_department: str | None = None,
        forced_persona_id: str | None = None,
        forced_scenario_id: str | None = None,
    ) -> TicketRecord:
        generated = self.generation_service.build_ticket(
            session_id=session_id,
            profile=profile,
            required_tags=required_tags,
            forced_tier=forced_tier,
            forced_ticket_type=forced_ticket_type,
            forced_department=forced_department,
            forced_persona_id=forced_persona_id,
            forced_scenario_id=forced_scenario_id,
        )

        zammad_ticket_id = None
        try:
            zammad_ticket_id = self.zammad_gateway.create_ticket(generated)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to create Zammad ticket: %s", exc)

        record = self.repository.create_ticket(
            session_id=session_id,
            subject=generated.subject,
            tier=generated.tier.value,
            priority=generated.priority.value,
            scenario_id=generated.scenario_id,
            hidden_truth=generated.hidden_truth,
            zammad_ticket_id=zammad_ticket_id,
        )

        self.repository.add_interaction(
            ticket_id=record.id,
            actor="customer",
            body=generated.body,
            metadata={"source": "generated", "zammad_ticket_id": zammad_ticket_id},
        )
        return record

    def _queue_window_tickets(
        self,
        pending_batches: list[dict[str, object]],
        profile: SessionProfile,
        window_index: int,
    ) -> None:
        baseline = self.rng.randint(profile.tickets_per_window_min, profile.tickets_per_window_max)
        if baseline > 0:
            pending_batches.append({"remaining": baseline, "required_tags": []})

        for injection in profile.incident_injections:
            if injection.at_window != window_index:
                continue
            if injection.extra_tickets > 0:
                pending_batches.append(
                    {
                        "remaining": injection.extra_tickets,
                        "required_tags": list(injection.scenario_tags),
                    }
                )
            logger.info(
                "Queued incident injection '%s' for window %s",
                injection.name,
                window_index,
            )

    def _emit_trickle_tickets(
        self,
        session_id: str,
        profile: SessionProfile,
        pending_batches: list[dict[str, object]],
    ) -> int:
        max_per_tick = profile.trickle_max_per_tick
        if max_per_tick <= 0:
            return 0

        created = 0
        remaining_budget = max_per_tick
        while remaining_budget > 0 and pending_batches:
            batch = pending_batches[0]
            remaining = int(batch.get("remaining", 0))
            required_tags = [str(tag) for tag in batch.get("required_tags", [])]

            if remaining <= 0:
                pending_batches.pop(0)
                continue

            to_emit = min(remaining, remaining_budget)
            for _ in range(to_emit):
                self._create_ticket(
                    session_id=session_id,
                    profile=profile,
                    required_tags=required_tags,
                )
            created += to_emit
            remaining_budget -= to_emit
            remaining -= to_emit

            if remaining <= 0:
                pending_batches.pop(0)
            else:
                batch["remaining"] = remaining

        return created

    @staticmethod
    def _normalize_pending_batches(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                remaining = int(item.get("remaining", 0))
            except (TypeError, ValueError):
                continue
            tags = item.get("required_tags", [])
            if remaining <= 0:
                continue
            if not isinstance(tags, list):
                tags = []
            normalized.append(
                {
                    "remaining": remaining,
                    "required_tags": [str(tag) for tag in tags],
                }
            )
        return normalized

    @staticmethod
    def _is_business_hour(timestamp) -> bool:
        # Monday-Friday, 09:00-17:00 in UTC for v1.
        weekday = timestamp.weekday()
        hour = timestamp.hour
        return weekday < 5 and 9 <= hour < 17

    @staticmethod
    def build_incident(name: str, at_window: int, extra_tickets: int, tags: list[str]) -> IncidentInjection:
        return IncidentInjection(
            name=name,
            at_window=at_window,
            extra_tickets=extra_tickets,
            scenario_tags=tags,
        )
