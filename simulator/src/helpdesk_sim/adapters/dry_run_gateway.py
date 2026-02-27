from __future__ import annotations

from collections import defaultdict

from helpdesk_sim.adapters.gateway import TicketArticle
from helpdesk_sim.domain.models import GeneratedTicket


class DryRunGateway:
    """In-memory adapter used for local simulator development and tests."""

    def __init__(self) -> None:
        self._next_ticket_id = 1000
        self._tickets: dict[int, dict[str, object]] = {}
        self._articles: defaultdict[int, list[TicketArticle]] = defaultdict(list)

    def create_ticket(self, ticket: GeneratedTicket) -> int:
        ticket_id = self._next_ticket_id
        self._next_ticket_id += 1
        self._tickets[ticket_id] = {
            "subject": ticket.subject,
            "closed": False,
        }
        self._articles[ticket_id].append(
            TicketArticle(id=1, body=ticket.body, sender="customer")
        )
        return ticket_id

    def fetch_new_articles(self, zammad_ticket_id: int, after_article_id: int) -> list[TicketArticle]:
        return [
            article
            for article in self._articles.get(zammad_ticket_id, [])
            if article.id > after_article_id
        ]

    def post_customer_reply(self, zammad_ticket_id: int, body: str, subject: str) -> None:
        next_id = len(self._articles.get(zammad_ticket_id, [])) + 1
        self._articles[zammad_ticket_id].append(
            TicketArticle(id=next_id, body=body, sender="customer")
        )

    def is_ticket_closed(self, zammad_ticket_id: int) -> bool:
        ticket = self._tickets.get(zammad_ticket_id)
        if ticket is None:
            return False
        return bool(ticket.get("closed", False))

    def delete_ticket(self, zammad_ticket_id: int) -> bool:
        existed = zammad_ticket_id in self._tickets
        self._tickets.pop(zammad_ticket_id, None)
        self._articles.pop(zammad_ticket_id, None)
        return existed

    def close_ticket(self, zammad_ticket_id: int) -> bool:
        ticket = self._tickets.get(zammad_ticket_id)
        if ticket is None:
            return False
        ticket["closed"] = True
        return True

    # Convenience for tests/manual simulation.
    def add_agent_reply(self, zammad_ticket_id: int, body: str) -> None:
        next_id = len(self._articles.get(zammad_ticket_id, [])) + 1
        self._articles[zammad_ticket_id].append(
            TicketArticle(id=next_id, body=body, sender="agent")
        )

    def close_ticket(self, zammad_ticket_id: int) -> None:
        if zammad_ticket_id in self._tickets:
            self._tickets[zammad_ticket_id]["closed"] = True
