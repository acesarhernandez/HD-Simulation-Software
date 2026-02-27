from datetime import timedelta

from helpdesk_sim.domain.models import HintLevel
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.hint_service import HintService
from helpdesk_sim.utils import utc_now


def test_hint_request_applies_penalty(tmp_path) -> None:
    repository = SimulatorRepository(tmp_path / "sim.db")
    repository.initialize()

    now = utc_now()
    session = repository.create_session(
        profile_name="normal_day",
        started_at=now,
        ends_at=now + timedelta(hours=8),
        next_window_at=now,
        config={
            "name": "normal_day",
            "duration_hours": 8,
            "cadence_minutes": 60,
            "tickets_per_window_min": 1,
            "tickets_per_window_max": 1,
            "tier_weights": {"tier1": 100},
            "scenario_type_weights": {},
            "incident_injections": [],
            "sla_policy": {"first_response_minutes": {}, "resolution_minutes": {}},
            "hint_policy": {
                "enabled": True,
                "penalties": {
                    "nudge": 2,
                    "guided_step": 5,
                    "strong_hint": 10,
                },
            },
        },
    )

    ticket = repository.create_ticket(
        session_id=session.id,
        subject="Test",
        tier="tier1",
        priority="normal",
        scenario_id="s1",
        hidden_truth={
            "hint_penalty_total": 0,
            "hint_bank": {"nudge": "Check account status first."},
        },
        zammad_ticket_id=1001,
    )

    service = HintService(repository)
    response = service.request_hint(ticket_id=ticket.id, level=HintLevel.nudge)

    updated = repository.get_ticket(ticket.id)
    assert response.penalty_applied == 2
    assert updated is not None
    assert updated.hidden_truth["hint_penalty_total"] == 2
