from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from helpdesk_sim.domain.models import GeneratedTicket


@dataclass(slots=True)
class TicketArticle:
    id: int
    body: str
    sender: str
    internal: bool = False

    @property
    def is_agent(self) -> bool:
        sender_lower = self.sender.lower()
        return "agent" in sender_lower or "system" in sender_lower

    @property
    def should_trigger_reply(self) -> bool:
        return self.is_agent and not self.internal


class ZammadGateway(Protocol):
    def create_ticket(self, ticket: GeneratedTicket) -> int | None:
        ...

    def fetch_new_articles(self, zammad_ticket_id: int, after_article_id: int) -> list[TicketArticle]:
        ...

    def post_customer_reply(self, zammad_ticket_id: int, body: str, subject: str) -> None:
        ...

    def is_ticket_closed(self, zammad_ticket_id: int) -> bool:
        ...

    def delete_ticket(self, zammad_ticket_id: int) -> bool:
        ...

    def close_ticket(self, zammad_ticket_id: int) -> bool:
        ...
