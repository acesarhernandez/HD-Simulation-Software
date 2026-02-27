from datetime import timedelta

from helpdesk_sim.domain.models import InteractionRecord, SessionProfile, TicketRecord
from helpdesk_sim.services.grading_service import GradingService
from helpdesk_sim.utils import utc_now


def test_grading_assigns_high_score_for_expected_resolution() -> None:
    now = utc_now()
    ticket = TicketRecord(
        id="t1",
        session_id="s1",
        zammad_ticket_id=1001,
        subject="Cannot sign in",
        tier="tier1",
        priority="normal",
        status="open",
        scenario_id="x",
        hidden_truth={
            "expected_agent_checks": ["verify password expiration", "check account lockout"],
            "acceptable_resolution_keywords": ["reset password", "unlock"],
            "root_cause": "password expired",
            "hint_penalty_total": 0,
        },
        created_at=now,
        updated_at=now,
        closed_at=now + timedelta(minutes=15),
        last_seen_article_id=2,
    )

    interactions = [
        InteractionRecord(
            id="i1",
            ticket_id="t1",
            actor="agent",
            body=(
                "Please verify password expiration and check account lockout. "
                "Impact: user blocked. Troubleshooting complete. Root cause identified. "
                "Resolution: reset password and unlock account."
            ),
            created_at=now + timedelta(minutes=5),
            metadata={},
        )
    ]

    profile = SessionProfile.model_validate(
        {
            "name": "normal_day",
            "duration_hours": 8,
            "cadence_minutes": 60,
            "tickets_per_window_min": 1,
            "tickets_per_window_max": 1,
            "tier_weights": {"tier1": 100},
            "scenario_type_weights": {},
            "incident_injections": [],
            "sla_policy": {
                "first_response_minutes": {"normal": 30},
                "resolution_minutes": {"normal": 120},
            },
            "hint_policy": {"enabled": True, "penalties": {}},
        }
    )

    result = GradingService().grade_ticket(ticket=ticket, interactions=interactions, profile=profile)

    assert result["score"]["total"] >= 80
    assert result["score"]["correctness"] >= 20
