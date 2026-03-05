from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from helpdesk_sim.domain.models import (
    KnowledgeArticleType,
    KnowledgeProposedAction,
    KnowledgeReviewDecisionRequest,
    KnowledgeReviewStatus,
    KnowledgeRevisionRequest,
)
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.catalog_service import CatalogService
from helpdesk_sim.services.knowledge_matcher_service import KnowledgeMatcherService
from helpdesk_sim.services.knowledge_proposal_service import KnowledgeProposalService
from helpdesk_sim.services.knowledge_provider_service import KnowledgeProviderService
from helpdesk_sim.services.knowledge_review_service import KnowledgeReviewService


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "helpdesk_sim" / "templates"


class _FakeProvider:
    publish_mode = "internal"

    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def validate_configuration(self) -> dict[str, object]:
        return {"provider": "zammad", "enabled": True, "ready": True}

    def list_sources(self) -> list[dict[str, object]]:
        return [{"id": "1", "name": "KB"}]

    def sync_index(self, source_id: str | None = None):
        return []

    def get_article(self, source_id: str | None, external_article_id: str):
        return None

    def create_article(self, draft):
        self.created.append({"title": draft.title, "body": draft.body_markdown})
        return {"external_article_id": "9001", "provider": "zammad"}

    def update_article(self, external_article_id: str, draft):
        self.created.append({"title": draft.title, "body": draft.body_markdown, "target": external_article_id})
        return {"external_article_id": external_article_id, "provider": "zammad"}

    def publish_article(self, external_article_id: str, publish_mode: str):
        return {"external_article_id": external_article_id, "provider": "zammad"}


def _build_services(tmp_path: Path):
    repository = SimulatorRepository(db_path=tmp_path / "kb-review.db")
    repository.initialize()
    catalog = CatalogService(templates_dir=TEMPLATES_DIR)
    catalog.load()
    provider = _FakeProvider()
    provider_service = KnowledgeProviderService(
        repository=repository,
        provider=provider,
        provider_name="zammad",
    )
    proposal_service = KnowledgeProposalService(
        repository=repository,
        catalog=catalog,
        matcher=KnowledgeMatcherService(),
        provider_service=provider_service,
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
    )
    review_service = KnowledgeReviewService(
        proposal_service=proposal_service,
        provider_service=provider_service,
        llm_enabled=False,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3:latest",
        review_required=True,
    )
    return repository, provider, review_service


def _create_review_item(repository: SimulatorRepository) -> str:
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
        hidden_truth={"root_cause": "Missing shared mailbox permission assignment in group membership."},
        zammad_ticket_id=700,
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
                "total": 75,
            },
            "metrics": {},
            "missed_checks": [],
        },
    )
    item = repository.create_kb_review_item(
        source_ticket_id=ticket.id,
        source_zammad_ticket_id=700,
        contributing_ticket_ids=[],
        provider="zammad",
        proposed_action=KnowledgeProposedAction.create_new,
        target_external_article_id=None,
        article_type=KnowledgeArticleType.troubleshooting,
        title="Shared Mailbox Access Management",
        summary="Mailbox troubleshooting steps.",
        tags=["email", "access"],
        body_markdown="## Purpose\nBase draft",
        diff_summary={"proposed_action": "create_new"},
        matching_rationale="No strong match found.",
        llm_confidence=0.75,
        kb_worthiness_score=80,
        kb_worthiness_reason="Repeatable issue",
        status=KnowledgeReviewStatus.needs_review,
    )
    return item.id


def test_kb_review_revision_creates_revision_record(tmp_path: Path) -> None:
    repository, _provider, review_service = _build_services(tmp_path)
    review_item_id = _create_review_item(repository)

    data = review_service.revise_review_item(
        review_item_id,
        KnowledgeRevisionRequest(instruction="Shorten this article and keep the scope tight."),
    )

    assert data["revision"]["revision_number"] == 1
    assert data["llm_used"] is False
    updated = repository.get_kb_review_item(review_item_id)
    assert updated is not None
    assert "Reviewer Revision Note" in updated.body_markdown


def test_kb_review_publish_requires_approval(tmp_path: Path) -> None:
    repository, _provider, review_service = _build_services(tmp_path)
    review_item_id = _create_review_item(repository)

    with pytest.raises(ValueError, match="Approve this KB proposal before publishing it"):
        review_service.publish_review_item(review_item_id)


def test_kb_review_publish_marks_item_published(tmp_path: Path) -> None:
    repository, provider, review_service = _build_services(tmp_path)
    review_item_id = _create_review_item(repository)

    review_service.approve_review_item(
        review_item_id,
        KnowledgeReviewDecisionRequest(notes="Looks good."),
    )
    data = review_service.publish_review_item(review_item_id)

    updated = repository.get_kb_review_item(review_item_id)
    assert updated is not None
    assert updated.status == KnowledgeReviewStatus.published
    assert updated.published_external_article_id == "9001"
    assert provider.created
    assert data["publish_result"]["published_external_article_id"] == "9001"
