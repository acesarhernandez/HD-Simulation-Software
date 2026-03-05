from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from helpdesk_sim.adapters.knowledge_base import DisabledKnowledgeBaseProvider
from helpdesk_sim.domain.models import KnowledgeArticleCacheEntry
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.catalog_service import CatalogService
from helpdesk_sim.services.knowledge_matcher_service import KnowledgeMatcherService
from helpdesk_sim.services.knowledge_proposal_service import KnowledgeProposalService
from helpdesk_sim.services.knowledge_provider_service import KnowledgeProviderService
from helpdesk_sim.utils import utc_now


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "helpdesk_sim" / "templates"


def _build_services(tmp_path: Path) -> tuple[SimulatorRepository, KnowledgeProposalService]:
    repository = SimulatorRepository(db_path=tmp_path / "kb-test.db")
    repository.initialize()

    catalog = CatalogService(templates_dir=TEMPLATES_DIR)
    catalog.load()

    provider_service = KnowledgeProviderService(
        repository=repository,
        provider=DisabledKnowledgeBaseProvider(reason="disabled in tests"),
        provider_name="zammad",
    )
    service = KnowledgeProposalService(
        repository=repository,
        catalog=catalog,
        matcher=KnowledgeMatcherService(),
        provider_service=provider_service,
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
        min_score=60,
    )
    return repository, service


def _create_closed_ticket(
    repository: SimulatorRepository,
    *,
    hidden_truth: dict[str, object],
    score_total: int,
) -> str:
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
        hidden_truth=hidden_truth,
        zammad_ticket_id=501,
    )
    repository.add_interaction(
        ticket.id,
        actor="customer",
        body="Our new coordinator can log in but cannot open the HR shared mailbox in Outlook.",
    )
    repository.add_interaction(
        ticket.id,
        actor="agent",
        body="Checked the account state and mailbox group membership.",
    )
    repository.close_ticket(
        ticket.id,
        score={
            "score": {
                "troubleshooting": 20,
                "correctness": 20,
                "communication": 10,
                "documentation": 10,
                "sla": 10,
                "escalation": 5,
                "hint_penalty": 0,
                "total": score_total,
            },
            "metrics": {},
            "missed_checks": [],
        },
    )
    return ticket.id


def test_kb_proposal_uses_existing_article_when_match_is_strong(tmp_path: Path) -> None:
    repository, service = _build_services(tmp_path)
    repository.replace_kb_article_cache(
        "zammad",
        [
            KnowledgeArticleCacheEntry(
                id="zammad:200",
                provider="zammad",
                external_article_id="200",
                external_kb_id="1",
                external_category_id="10",
                locale_id="1",
                title="Shared Mailbox Access Management",
                summary="Mailbox permission groups and Outlook refresh steps.",
                body_markdown="Existing article body",
                tags=["email", "access"],
                status="internal",
                fingerprint="abc",
                last_synced_at=utc_now(),
                version_token="1",
            )
        ],
    )
    ticket_id = _create_closed_ticket(
        repository,
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
            "knowledge_article_ids": ["kb_shared_mailbox_access"],
            "persona": {"role": "HR"},
        },
        score_total=78,
    )

    data = service.propose_for_ticket(ticket_id)
    review_item = data["review_item"]

    assert review_item["proposed_action"] in {"append_scenario", "update_existing"}
    assert review_item["target_external_article_id"] == "200"
    assert review_item["status"] in {"needs_review", "needs_target_review"}


def test_kb_proposal_can_be_created_even_when_not_recommended(tmp_path: Path) -> None:
    repository, service = _build_services(tmp_path)
    ticket_id = _create_closed_ticket(
        repository,
        hidden_truth={
            "ticket_type": "endpoint_issue",
            "root_cause": "",
            "expected_agent_checks": [],
            "resolution_steps": [],
            "knowledge_article_ids": [],
            "persona": {"role": "HR"},
        },
        score_total=20,
    )

    data = service.propose_for_ticket(ticket_id)
    review_item = data["review_item"]

    assert review_item["proposed_action"] == "not_recommended"
    assert review_item["status"] == "draft"
    assert review_item["kb_worthiness_score"] < 60
