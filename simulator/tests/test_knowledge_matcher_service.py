from __future__ import annotations

from datetime import UTC, datetime

from helpdesk_sim.domain.models import (
    KnowledgeArticle,
    KnowledgeArticleCacheEntry,
    TicketPriority,
    TicketRecord,
    TicketStatus,
    TicketTier,
)
from helpdesk_sim.services.knowledge_matcher_service import KnowledgeMatcherService


def test_knowledge_matcher_ranks_related_article_first() -> None:
    now = datetime.now(UTC)
    ticket = TicketRecord(
        id="ticket-1",
        session_id="session-1",
        zammad_ticket_id=101,
        subject="New HR coordinator cannot open shared mailbox",
        tier=TicketTier.tier1,
        priority=TicketPriority.normal,
        status=TicketStatus.closed,
        scenario_id="shared-mailbox",
        hidden_truth={
            "ticket_type": "access_request",
            "tags": ["email", "access"],
        },
        score={"score": {"total": 72}},
        created_at=now,
        updated_at=now,
        closed_at=now,
        last_seen_article_id=0,
    )
    linked_articles = [
        KnowledgeArticle(
            id="kb_shared_mailbox_access",
            title="Shared Mailbox Access Management",
            url="https://kb.example.local/shared-mailbox-access",
            summary="Mailbox permission groups and Outlook refresh steps.",
            tags=["email", "access"],
        )
    ]
    cached_articles = [
        KnowledgeArticleCacheEntry(
            id="zammad:200",
            provider="zammad",
            external_article_id="200",
            external_kb_id="1",
            external_category_id="10",
            locale_id="1",
            title="Shared Mailbox Access Management",
            summary="Mailbox permission groups and Outlook refresh steps.",
            body_markdown="Use this when a user cannot access the shared mailbox.",
            tags=["email", "access"],
            status="internal",
            fingerprint="abc",
            last_synced_at=now,
            version_token="1",
        ),
        KnowledgeArticleCacheEntry(
            id="zammad:201",
            provider="zammad",
            external_article_id="201",
            external_kb_id="1",
            external_category_id="10",
            locale_id="1",
            title="Password Reset and Unlock Procedure",
            summary="Password resets and lockout handling.",
            body_markdown="Reset passwords and unlock accounts.",
            tags=["identity"],
            status="internal",
            fingerprint="def",
            last_synced_at=now,
            version_token="1",
        ),
    ]

    ranked = KnowledgeMatcherService().rank_candidates(
        ticket=ticket,
        cached_articles=cached_articles,
        linked_articles=linked_articles,
    )

    assert ranked
    assert ranked[0]["article"].external_article_id == "200"
    assert int(ranked[0]["score"]) > int(ranked[-1]["score"])
