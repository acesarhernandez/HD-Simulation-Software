from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from helpdesk_sim.domain.models import ScoreMode
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.report_service import ReportService


def _close_ticket(
    repository: SimulatorRepository,
    session_id: str,
    *,
    subject: str,
    score_mode: str,
    total_score: int,
) -> None:
    ticket = repository.create_ticket(
        session_id=session_id,
        subject=subject,
        tier="tier1",
        priority="normal",
        scenario_id="t1_password_reset",
        hidden_truth={"ticket_type": "password_reset"},
        zammad_ticket_id=None,
    )
    repository.close_ticket(
        ticket.id,
        score={
            "score": {
                "troubleshooting": total_score,
                "correctness": 0,
                "communication": 0,
                "documentation": 0,
                "sla": 0,
                "escalation": 0,
                "hint_penalty": 0,
                "total": total_score,
            },
            "metrics": {
                "first_response_minutes": 5.0,
                "resolution_minutes": 15.0,
            },
            "missed_checks": [],
            "meta": {
                "score_mode": score_mode,
                "god_mode_used": score_mode == ScoreMode.guided_training.value,
            },
        },
    )


def test_report_service_filters_by_score_mode(tmp_path: Path) -> None:
    repository = SimulatorRepository(db_path=tmp_path / "report.db")
    repository.initialize()

    now = datetime.now(UTC)
    session = repository.create_session(
        profile_name="manual_only",
        started_at=now,
        ends_at=now + timedelta(hours=8),
        next_window_at=now,
        config={"name": "manual_only"},
    )

    _close_ticket(
        repository,
        session.id,
        subject="Practice ticket",
        score_mode=ScoreMode.practice.value,
        total_score=80,
    )
    _close_ticket(
        repository,
        session.id,
        subject="Guided ticket",
        score_mode=ScoreMode.guided_training.value,
        total_score=60,
    )

    service = ReportService(repository)

    practice = service.generate("daily", score_mode=ScoreMode.practice.value)
    guided = service.generate("daily", score_mode=ScoreMode.guided_training.value)

    assert practice["tickets_closed"] == 1
    assert guided["tickets_closed"] == 1
    assert practice["score_mode"] == ScoreMode.practice.value
    assert guided["score_mode"] == ScoreMode.guided_training.value

    practice_saved = repository.latest_report("daily")
    guided_saved = repository.latest_report("daily_god")
    assert practice_saved is not None
    assert guided_saved is not None
