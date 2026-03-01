from __future__ import annotations

from datetime import UTC, datetime

from helpdesk_sim.domain.models import InteractionRecord, TicketPriority, TicketRecord, TicketStatus, TicketTier
from helpdesk_sim.services import coaching_service
from helpdesk_sim.services.coaching_service import CoachingService


def _sample_ticket() -> TicketRecord:
    now = datetime.now(UTC)
    return TicketRecord(
        id="ticket-1",
        session_id="session-1",
        zammad_ticket_id=123,
        subject="New HR coordinator cannot open shared mailbox",
        tier=TicketTier.tier1,
        priority=TicketPriority.normal,
        status=TicketStatus.closed,
        scenario_id="t1_mailbox",
        hidden_truth={},
        score={
            "score": {
                "troubleshooting": 10,
                "correctness": 8,
                "communication": 12,
                "documentation": 4,
                "sla": 10,
                "escalation": 5,
                "hint_penalty": 0,
                "total": 49,
            },
            "metrics": {
                "first_response_minutes": 4.0,
                "resolution_minutes": 22.0,
            },
            "missed_checks": ["check shared mailbox permissions", "confirm group membership"],
        },
        created_at=now,
        updated_at=now,
        closed_at=now,
        last_seen_article_id=3,
    )


def _sample_interactions() -> list[InteractionRecord]:
    now = datetime.now(UTC)
    return [
        InteractionRecord(
            id="1",
            ticket_id="ticket-1",
            actor="agent",
            body="Please confirm whether the mailbox is missing in Outlook.",
            created_at=now,
            metadata={},
        )
    ]


def test_coaching_service_returns_deterministic_feedback_without_llm() -> None:
    service = CoachingService(
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )

    result = service.generate_ticket_coaching(_sample_ticket(), _sample_interactions())

    assert result["llm_used"] is False
    assert "total score 49" in str(result["coaching_note"]).lower()
    assert result["strengths"]
    assert result["focus_areas"]
    assert "missing explicit coverage" in str(result["documentation_critique"]).lower()


def test_coaching_service_uses_ollama_when_available(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"response": "Focus on validating mailbox permissions before closing similar tickets."}

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

    monkeypatch.setattr(coaching_service.httpx, "Client", FakeClient)

    service = CoachingService(
        llm_enabled=True,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )

    result = service.generate_ticket_coaching(_sample_ticket(), _sample_interactions())

    assert result["llm_used"] is True
    assert result["coaching_note"] == "Focus on validating mailbox permissions before closing similar tickets."
