from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from helpdesk_sim.domain.models import ScoreMode
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.coaching_service import CoachingService
from helpdesk_sim.services.god_mode_service import GodModeService
from helpdesk_sim.services.mentor_service import MentorService


def _build_service(tmp_path: Path) -> tuple[SimulatorRepository, GodModeService]:
    repository = SimulatorRepository(db_path=tmp_path / "god-mode.db")
    repository.initialize()

    mentor = MentorService(
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )
    coaching = CoachingService(
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )
    service = GodModeService(
        repository=repository,
        mentor_service=mentor,
        coaching_service=coaching,
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )
    return repository, service


def _create_ticket(repository: SimulatorRepository) -> str:
    now = datetime.now(UTC)
    session = repository.create_session(
        profile_name="manual_only",
        started_at=now,
        ends_at=now + timedelta(hours=8),
        next_window_at=now,
        config={"name": "manual_only"},
    )
    ticket = repository.create_ticket(
        session_id=session.id,
        subject="New HR coordinator cannot open shared mailbox",
        tier="tier1",
        priority="normal",
        scenario_id="t1_shared_mailbox_access",
        hidden_truth={
            "ticket_type": "access_request",
            "root_cause": "Missing shared mailbox permission assignment in group membership.",
            "expected_agent_checks": [
                "verify account active",
                "check shared mailbox permissions",
                "confirm group membership",
            ],
            "resolution_steps": [
                "Add user to mailbox access group",
                "Ask user to restart Outlook",
            ],
        },
        zammad_ticket_id=777,
    )
    return ticket.id


def test_god_mode_start_creates_walkthrough_state(tmp_path: Path) -> None:
    repository, service = _build_service(tmp_path)
    ticket_id = _create_ticket(repository)

    walkthrough = service.start_ticket(ticket_id=ticket_id, attempt_first=True)

    assert walkthrough["started"] is True
    assert walkthrough["attempt_first"] is True
    assert walkthrough["current_phase"] == "intake_ownership"
    assert len(walkthrough["phases"]) == 10

    stored_ticket = repository.get_ticket(ticket_id)
    assert stored_ticket is not None
    hidden = stored_ticket.hidden_truth
    assert isinstance(hidden, dict)
    assert hidden["god_mode"]["enabled"] is True


def test_god_mode_identity_gate_blocks_until_attempt_passes(tmp_path: Path) -> None:
    repository, service = _build_service(tmp_path)
    ticket_id = _create_ticket(repository)
    service.start_ticket(ticket_id=ticket_id, attempt_first=True)

    with pytest.raises(ValueError, match="phase gate is not complete"):
        service.advance_phase(ticket_id=ticket_id, phase_key="identity_security")

    result = service.submit_attempt(
        ticket_id=ticket_id,
        phase_key="identity_security",
        text="I will verify identity first and confirm username plus MFA before any access changes.",
    )

    assert result["can_advance"] is True
    advanced = service.advance_phase(ticket_id=ticket_id, phase_key="identity_security")
    assert advanced["advanced"] is True


def test_god_mode_tags_scores_as_guided_training(tmp_path: Path) -> None:
    repository, service = _build_service(tmp_path)
    ticket_id = _create_ticket(repository)
    service.start_ticket(ticket_id=ticket_id, attempt_first=False)

    ticket = repository.get_ticket(ticket_id)
    assert ticket is not None

    payload = service.tag_score_payload(
        ticket,
        {
            "score": {"total": 90},
            "metrics": {},
            "missed_checks": [],
        },
    )
    assert payload["meta"]["score_mode"] == ScoreMode.guided_training.value
    assert payload["meta"]["god_mode_used"] is True
