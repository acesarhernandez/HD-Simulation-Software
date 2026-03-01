from __future__ import annotations

from types import SimpleNamespace

from helpdesk_sim.domain.models import SessionProfile, TicketPriority, TicketTier
from helpdesk_sim.services import generation_service
from helpdesk_sim.services.generation_service import GenerationService


class _FakeCatalog:
    def __init__(self) -> None:
        self._scenario = SimpleNamespace(
            id="scenario-1",
            title="New HR coordinator cannot open shared mailbox",
            ticket_type="access_request",
            priority=TicketPriority.normal,
            customer_problem="Our new coordinator can log in but cannot open the HR shared mailbox in Outlook.",
            root_cause="Missing shared mailbox permission assignment in group membership.",
            expected_agent_checks=["verify account active", "check shared mailbox permissions"],
            resolution_steps=["Add user to mailbox access group"],
            acceptable_resolution_keywords=["mailbox permission", "add to group"],
            knowledge_article_ids=[],
            clue_map={"account": "She can log in to email and Teams, just not the shared mailbox."},
            hint_bank={},
            default_follow_up="I can share more details if you can tell me exactly what you need.",
        )
        self._persona = SimpleNamespace(
            id="hr_01",
            role="HR",
            full_name="Emily Carter",
            email="emily.carter@bmm.local",
            technical_level="medium",
            tone="direct",
        )

    def pick_scenario(self, **kwargs):
        return self._scenario

    def pick_persona(self, *args, **kwargs):
        return self._persona


def _profile() -> SessionProfile:
    return SessionProfile(
        name="manual_only",
        duration_hours=8,
        cadence_minutes=30,
        tickets_per_window_min=0,
        tickets_per_window_max=0,
        tier_weights={TicketTier.tier1: 100, TicketTier.tier2: 0, TicketTier.sysadmin: 0},
        scenario_type_weights={},
        incident_injections=[],
        sla_policy={"first_response_minutes": {}, "resolution_minutes": {}},
    )


def test_generation_service_keeps_template_opening_when_llm_disabled() -> None:
    service = GenerationService(
        catalog=_FakeCatalog(),
        llm_enabled=False,
    )

    ticket = service.build_ticket(session_id="session-1", profile=_profile())

    assert ticket.body == "Our new coordinator can log in but cannot open the HR shared mailbox in Outlook."
    assert ticket.hidden_truth["opening_body_source"] == "template"
    assert ticket.hidden_truth["root_cause"] == "Missing shared mailbox permission assignment in group membership."


def test_generation_service_rewrites_opening_when_llm_available(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"response": "Our HR coordinator can access email, but Outlook will not open the shared HR mailbox on her company laptop."}

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

    monkeypatch.setattr(generation_service.httpx, "Client", FakeClient)

    service = GenerationService(
        catalog=_FakeCatalog(),
        llm_enabled=True,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
        rewrite_opening_tickets=True,
    )

    ticket = service.build_ticket(session_id="session-1", profile=_profile())

    assert ticket.body.startswith("Our HR coordinator can access email")
    assert ticket.hidden_truth["opening_body_source"] == "llm_rewrite"
    assert ticket.hidden_truth["template_body"] == "Our new coordinator can log in but cannot open the HR shared mailbox in Outlook."
    assert ticket.hidden_truth["root_cause"] == "Missing shared mailbox permission assignment in group membership."


def test_generation_service_falls_back_to_template_when_llm_fails(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        @staticmethod
        def post(*args, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(generation_service.httpx, "Client", FakeClient)

    service = GenerationService(
        catalog=_FakeCatalog(),
        llm_enabled=True,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
        rewrite_opening_tickets=True,
    )

    ticket = service.build_ticket(session_id="session-1", profile=_profile())

    assert ticket.body == "Our new coordinator can log in but cannot open the HR shared mailbox in Outlook."
    assert ticket.hidden_truth["opening_body_source"] == "template"
