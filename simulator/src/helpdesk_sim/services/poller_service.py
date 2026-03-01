from __future__ import annotations

import logging

from helpdesk_sim.adapters.gateway import ZammadGateway
from helpdesk_sim.domain.models import SessionProfile
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.grading_service import GradingService
from helpdesk_sim.services.response_engine import ResponseEngine

logger = logging.getLogger(__name__)


class PollerService:
    def __init__(
        self,
        repository: SimulatorRepository,
        zammad_gateway: ZammadGateway,
        response_engine: ResponseEngine,
        grading_service: GradingService,
    ) -> None:
        self.repository = repository
        self.zammad_gateway = zammad_gateway
        self.response_engine = response_engine
        self.grading_service = grading_service

    def tick(self) -> dict[str, int]:
        open_tickets = self.repository.list_open_tickets()
        processed = 0
        replies_sent = 0
        closed_count = 0

        for ticket in open_tickets:
            if ticket.zammad_ticket_id is None:
                continue

            processed += 1
            try:
                articles = self.zammad_gateway.fetch_new_articles(
                    zammad_ticket_id=ticket.zammad_ticket_id,
                    after_article_id=ticket.last_seen_article_id,
                )
            except Exception as exc:  # pragma: no cover - network failure path
                logger.exception("Failed to poll articles for ticket %s: %s", ticket.id, exc)
                continue

            max_article_id = ticket.last_seen_article_id
            for article in articles:
                max_article_id = max(max_article_id, article.id)
                if not article.should_trigger_reply:
                    continue

                self.repository.add_interaction(
                    ticket_id=ticket.id,
                    actor="agent",
                    body=article.body,
                    metadata={"article_id": article.id},
                )

                recent_interactions = [
                    row.model_dump(mode="json")
                    for row in self.repository.list_interactions(ticket.id)[-6:]
                ]

                user_reply = self.response_engine.generate_reply(
                    agent_message=article.body,
                    hidden_truth=ticket.hidden_truth,
                    recent_interactions=recent_interactions,
                )

                try:
                    self.zammad_gateway.post_customer_reply(
                        zammad_ticket_id=ticket.zammad_ticket_id,
                        body=user_reply,
                        subject=f"Re: {ticket.subject}",
                    )
                    replies_sent += 1
                except Exception as exc:  # pragma: no cover - network failure path
                    logger.exception("Failed to post customer reply for ticket %s: %s", ticket.id, exc)
                    continue

                self.repository.add_interaction(
                    ticket_id=ticket.id,
                    actor="customer",
                    body=user_reply,
                    metadata={"event": "simulated_reply", "article_id": article.id},
                )

            if max_article_id > ticket.last_seen_article_id:
                self.repository.update_ticket_last_seen_article_id(ticket.id, max_article_id)

            try:
                is_closed = self.zammad_gateway.is_ticket_closed(ticket.zammad_ticket_id)
            except Exception as exc:  # pragma: no cover - network failure path
                logger.exception("Failed to read state for ticket %s: %s", ticket.id, exc)
                continue

            if is_closed:
                self._finalize_ticket(ticket.id)
                closed_count += 1

        return {
            "tickets_checked": processed,
            "replies_sent": replies_sent,
            "tickets_closed": closed_count,
        }

    def _finalize_ticket(self, ticket_id: str) -> None:
        ticket = self.repository.get_ticket(ticket_id)
        if ticket is None:
            return

        interactions = self.repository.list_interactions(ticket_id)
        session = self.repository.get_session(ticket.session_id)
        if session is None:
            return

        profile = SessionProfile.model_validate(session.config)
        result = self.grading_service.grade_ticket(
            ticket=ticket,
            interactions=interactions,
            profile=profile,
        )

        self.repository.close_ticket(ticket_id=ticket_id, score=result)
        logger.info("Ticket %s closed and graded", ticket_id)
