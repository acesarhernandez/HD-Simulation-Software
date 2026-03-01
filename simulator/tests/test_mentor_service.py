from __future__ import annotations

from datetime import UTC, datetime

from helpdesk_sim.domain.models import InteractionRecord, TicketPriority, TicketRecord, TicketStatus, TicketTier
from helpdesk_sim.services import mentor_service
from helpdesk_sim.services.mentor_service import MentorService


def _sample_ticket() -> TicketRecord:
    now = datetime.now(UTC)
    return TicketRecord(
        id="ticket-1",
        session_id="session-1",
        zammad_ticket_id=123,
        subject="New HR coordinator cannot open shared mailbox",
        tier=TicketTier.tier1,
        priority=TicketPriority.normal,
        status=TicketStatus.open,
        scenario_id="t1_mailbox",
        hidden_truth={
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
        score=None,
        created_at=now,
        updated_at=now,
        closed_at=None,
        last_seen_article_id=2,
    )


def _sample_interactions() -> list[InteractionRecord]:
    now = datetime.now(UTC)
    return [
        InteractionRecord(
            id="1",
            ticket_id="ticket-1",
            actor="customer",
            body="She can log in to email and Teams, just not the shared mailbox.",
            created_at=now,
            metadata={},
        )
    ]


def test_mentor_service_returns_deterministic_guidance_without_llm() -> None:
    service = MentorService(
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )

    result = service.request_guidance(
        _sample_ticket(),
        _sample_interactions(),
        "What would you check next before I close this?",
    )

    assert result["llm_used"] is False
    assert "likely technical cause" in str(result["mentor_reply"]).lower()
    assert "missing shared mailbox permission assignment" in str(result["mentor_reply"]).lower()


def test_mentor_service_can_coach_on_communication_without_llm() -> None:
    service = MentorService(
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )

    result = service.request_guidance(
        _sample_ticket(),
        _sample_interactions(),
        "How should I word my reply so it sounds professional and easier for the user to answer?",
    )

    reply = str(result["mentor_reply"]).lower()
    assert result["llm_used"] is False
    assert "keep the reply professional" in reply
    assert "ask one or two narrow follow-up questions" in reply


def test_mentor_service_can_coach_on_sla_without_llm() -> None:
    service = MentorService(
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )

    result = service.request_guidance(
        _sample_ticket(),
        _sample_interactions(),
        "Am I at risk of missing SLA and what should I do next?",
    )

    reply = str(result["mentor_reply"]).lower()
    assert result["llm_used"] is False
    assert "manage it against the configured sla" in reply
    assert "do not close the ticket" in reply


def test_mentor_service_uses_ollama_when_available(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"response": "Check mailbox permissions first, then verify the user was added to the correct access group."}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        @staticmethod
        def post(*args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(mentor_service.httpx, "Client", FakeClient)

    service = MentorService(
        llm_enabled=True,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )

    result = service.request_guidance(
        _sample_ticket(),
        _sample_interactions(),
        "What would you check next before I close this?",
    )

    assert result["llm_used"] is True
    assert str(result["mentor_reply"]).startswith("Check mailbox permissions first")
