from __future__ import annotations

import re
from dataclasses import dataclass

from helpdesk_sim.domain.models import KnowledgeArticle, KnowledgeArticleCacheEntry, TicketRecord


@dataclass(slots=True)
class KnowledgeMatcherService:
    def rank_candidates(
        self,
        *,
        ticket: TicketRecord,
        cached_articles: list[KnowledgeArticleCacheEntry],
        linked_articles: list[KnowledgeArticle],
    ) -> list[dict[str, object]]:
        subject_tokens = self._tokenize(ticket.subject)
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        ticket_type = str(hidden.get("ticket_type", "")).strip().lower()
        scenario_tags = [str(item).strip().lower() for item in hidden.get("tags", []) if str(item).strip()]
        linked_token_pool = {
            token
            for article in linked_articles
            for token in (
                self._tokenize(article.title)
                | self._tokenize(article.summary)
                | {str(tag).strip().lower() for tag in article.tags}
            )
        }

        ranked: list[dict[str, object]] = []
        for article in cached_articles:
            article_tokens = (
                self._tokenize(article.title)
                | self._tokenize(article.summary)
                | self._tokenize(article.body_markdown)
                | {str(tag).strip().lower() for tag in article.tags}
            )
            overlap = len(subject_tokens & article_tokens)
            score = overlap * 12
            reasons: list[str] = []

            if overlap:
                reasons.append(f"title/summary token overlap ({overlap})")

            if linked_token_pool:
                linked_overlap = len(linked_token_pool & article_tokens)
                if linked_overlap:
                    score += 18 + (linked_overlap * 4)
                    reasons.append(f"matches linked KB guidance ({linked_overlap})")

            if ticket_type and ticket_type.replace("_", " ") in article.title.lower():
                score += 18
                reasons.append("ticket type appears in article title")

            if scenario_tags:
                tag_overlap = len(set(scenario_tags) & set(str(tag).lower() for tag in article.tags))
                if tag_overlap:
                    score += 10 + (tag_overlap * 3)
                    reasons.append(f"scenario tags match article tags ({tag_overlap})")

            if score <= 0:
                continue

            ranked.append(
                {
                    "article": article,
                    "score": score,
                    "reasons": reasons,
                }
            )

        ranked.sort(key=lambda item: (int(item["score"]), str(item["article"].title).lower()), reverse=True)
        return ranked[:5]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]{3,}", str(text).lower())}
