from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from helpdesk_sim.domain.models import (
    InteractionRecord,
    KnowledgeArticle,
    KnowledgeArticleCacheEntry,
    KnowledgeArticleType,
    KnowledgeProposedAction,
    KnowledgeReviewStatus,
    TicketRecord,
)
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.catalog_service import CatalogService
from helpdesk_sim.services.engine_control_client import EngineReadinessCoordinator
from helpdesk_sim.services.knowledge_matcher_service import KnowledgeMatcherService
from helpdesk_sim.services.knowledge_provider_service import KnowledgeProviderService


@dataclass(slots=True)
class KnowledgeProposalService:
    repository: SimulatorRepository
    catalog: CatalogService
    matcher: KnowledgeMatcherService
    provider_service: KnowledgeProviderService
    llm_enabled: bool
    ollama_url: str
    ollama_model: str
    min_score: int = 60
    timeout_seconds: float = 25.0
    engine_readiness: EngineReadinessCoordinator | None = None

    def propose_for_ticket(self, ticket_id: str) -> dict[str, object]:
        ticket = self.repository.get_ticket(ticket_id)
        if ticket is None:
            raise ValueError("ticket not found")
        if ticket.status.value != "closed":
            raise ValueError("close this ticket before creating a KB proposal")

        interactions = self.repository.list_interactions(ticket_id)
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        linked_ids = hidden.get("knowledge_article_ids", [])
        if not isinstance(linked_ids, list):
            linked_ids = []
        linked_articles = self.catalog.get_knowledge_articles([str(item) for item in linked_ids])
        cached_articles = self.repository.list_kb_article_cache(self.provider_service.provider_name)
        ranked = self.matcher.rank_candidates(
            ticket=ticket,
            cached_articles=cached_articles,
            linked_articles=linked_articles,
        )
        ranked = self._apply_lineage_bonus(ticket=ticket, ranked=ranked)

        worthiness = self._evaluate_kb_worthiness(ticket=ticket, interactions=interactions)
        article_type = self._determine_article_type(ticket=ticket)
        decision = self._decide_action(
            ticket=ticket,
            ranked=ranked,
            linked_articles=linked_articles,
            worthiness=worthiness,
        )
        target_article = decision["target_article"]
        contributing_ticket_ids = self._collect_contributing_ticket_ids(target_article)
        title = self._build_title(ticket=ticket, target_article=target_article)
        summary = self._build_summary(ticket=ticket, interactions=interactions, target_article=target_article)
        tags = self._build_tags(ticket=ticket, target_article=target_article)
        body_markdown = self._build_draft_body(
            ticket=ticket,
            interactions=interactions,
            article_type=article_type,
            proposed_action=decision["action"],
            target_article=target_article,
            linked_articles=linked_articles,
            contributing_ticket_ids=contributing_ticket_ids,
        )
        diff_summary = self._build_diff_summary(
            ticket=ticket,
            target_article=target_article,
            proposed_action=decision["action"],
            interactions=interactions,
        )

        llm_error = None
        if self.llm_enabled:
            try:
                llm_body = self._rewrite_draft_with_llm(
                    ticket=ticket,
                    interactions=interactions,
                    article_type=article_type,
                    proposed_action=decision["action"],
                    title=title,
                    summary=summary,
                    body_markdown=body_markdown,
                    target_article=target_article,
                )
                if llm_body:
                    body_markdown = llm_body
                    diff_summary["llm_rewrite"] = True
            except Exception as exc:  # pragma: no cover - network failure path
                llm_error = str(exc)
                diff_summary["llm_rewrite"] = False
                diff_summary["llm_error"] = llm_error

        review_item = self.repository.create_kb_review_item(
            source_ticket_id=ticket.id,
            source_zammad_ticket_id=ticket.zammad_ticket_id,
            contributing_ticket_ids=contributing_ticket_ids,
            provider=self.provider_service.provider_name,
            proposed_action=decision["action"],
            target_external_article_id=target_article.external_article_id if target_article else None,
            article_type=article_type,
            title=title,
            summary=summary,
            tags=tags,
            body_markdown=body_markdown,
            diff_summary=diff_summary,
            matching_rationale=str(decision["rationale"]),
            llm_confidence=float(decision["confidence"]),
            kb_worthiness_score=worthiness["score"],
            kb_worthiness_reason=worthiness["reason"],
            status=self._status_for_action(decision["action"]),
        )
        self.repository.add_kb_review_event(
            review_item.id,
            event_type="created",
            actor="system",
            notes="KB proposal created from a closed ticket.",
            metadata={
                "source_ticket_id": ticket.id,
                "source_zammad_ticket_id": ticket.zammad_ticket_id,
                "llm_error": llm_error,
            },
        )
        detail = self.get_review_detail(review_item.id)
        detail["english_summary"] = self._proposal_summary(
            review_item_id=review_item.id,
            action=decision["action"],
            worthiness=worthiness,
            target_article=target_article,
        )
        return detail

    def get_review_detail(self, review_item_id: str) -> dict[str, object]:
        review_item = self.repository.get_kb_review_item(review_item_id)
        if review_item is None:
            raise ValueError("KB review item not found")

        target_article = None
        if review_item.target_external_article_id:
            target_article = self.repository.get_kb_article_cache_by_external(
                review_item.provider,
                review_item.target_external_article_id,
            )

        revisions = self.repository.list_kb_review_revisions(review_item_id)
        events = self.repository.list_kb_review_events(review_item_id)
        source_ticket = self.repository.get_ticket(review_item.source_ticket_id)
        contributing = []
        for ticket_id in review_item.contributing_ticket_ids:
            ticket = self.repository.get_ticket(ticket_id)
            if ticket is not None:
                contributing.append(ticket.model_dump(mode="json"))

        return {
            "review_item": review_item.model_dump(mode="json"),
            "source_ticket": source_ticket.model_dump(mode="json") if source_ticket else None,
            "contributing_tickets": contributing,
            "target_article": target_article.model_dump(mode="json") if target_article else None,
            "revisions": [row.model_dump(mode="json") for row in revisions],
            "events": [row.model_dump(mode="json") for row in events],
        }

    def _apply_lineage_bonus(
        self,
        *,
        ticket: TicketRecord,
        ranked: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        if not ranked:
            return ranked

        previous_items = self.repository.list_kb_review_items(provider=self.provider_service.provider_name)
        scenario_matches: dict[str, int] = {}
        for item in previous_items:
            external_id = item.published_external_article_id or item.target_external_article_id
            if not external_id:
                continue
            prior_ticket = self.repository.get_ticket(item.source_ticket_id)
            if prior_ticket is None or prior_ticket.scenario_id != ticket.scenario_id:
                continue
            scenario_matches[external_id] = scenario_matches.get(external_id, 0) + 1

        if not scenario_matches:
            return ranked

        boosted: list[dict[str, object]] = []
        for row in ranked:
            article = row.get("article")
            if not isinstance(article, KnowledgeArticleCacheEntry):
                boosted.append(row)
                continue
            bonus_count = scenario_matches.get(article.external_article_id, 0)
            if not bonus_count:
                boosted.append(row)
                continue
            reasons = list(row.get("reasons", []))
            reasons.append(f"previous published scenario lineage ({bonus_count})")
            boosted.append(
                {
                    **row,
                    "score": int(row.get("score", 0)) + (bonus_count * 25),
                    "reasons": reasons,
                }
            )

        boosted.sort(
            key=lambda item: (
                int(item["score"]),
                str(item["article"].title).lower(),
            ),
            reverse=True,
        )
        return boosted[:5]

    def _evaluate_kb_worthiness(
        self,
        *,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
    ) -> dict[str, object]:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        score_payload = ticket.score if isinstance(ticket.score, dict) else {}
        score_block = score_payload.get("score", {}) if isinstance(score_payload.get("score", {}), dict) else {}
        total_score = int(score_block.get("total", 0) or 0)
        expected_checks = [str(item).strip() for item in hidden.get("expected_agent_checks", []) if str(item).strip()]
        resolution_steps = [str(item).strip() for item in hidden.get("resolution_steps", []) if str(item).strip()]
        knowledge_ids = [str(item).strip() for item in hidden.get("knowledge_article_ids", []) if str(item).strip()]
        root_cause = str(hidden.get("root_cause", "")).strip()
        ticket_type = str(hidden.get("ticket_type", "")).strip().lower()
        agent_messages = [row.body.strip() for row in interactions if row.actor == "agent" and row.body.strip()]

        score = 0
        reasons: list[str] = []
        if total_score >= self.min_score:
            score += 35
            reasons.append(f"ticket score {total_score} is above the KB threshold")
        elif total_score > 0:
            score += min(total_score // 2, 25)
            reasons.append(f"ticket score {total_score} contributes partial KB value")
        else:
            reasons.append("ticket has no completed scoring yet")

        if knowledge_ids:
            score += 20
            reasons.append("scenario is already linked to a KB domain")
        if ticket_type in {"access_request", "onboarding", "offboarding"}:
            score += 15
            reasons.append("ticket type maps to a repeatable operational process")
        if len(expected_checks) >= 2:
            score += 10
            reasons.append("scenario contains repeatable validation steps")
        if resolution_steps:
            score += 10
            reasons.append("scenario contains documented resolution steps")
        if root_cause:
            score += 5
            reasons.append("root cause is known")
        if agent_messages:
            score += 5
            reasons.append("analyst notes exist to support a usable article")

        score = min(score, 100)
        recommended = score >= self.min_score and bool(root_cause and resolution_steps)
        if not recommended:
            reasons.append(
                "the ticket can still be drafted manually, but it is not strongly recommended for publishing"
            )
        return {
            "score": score,
            "recommended": recommended,
            "reason": "; ".join(reasons),
        }

    def _determine_article_type(self, *, ticket: TicketRecord) -> KnowledgeArticleType:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        ticket_type = str(hidden.get("ticket_type", "")).strip().lower()
        if ticket_type in {"access_request", "onboarding", "offboarding"}:
            return KnowledgeArticleType.how_to
        return KnowledgeArticleType.troubleshooting

    def _decide_action(
        self,
        *,
        ticket: TicketRecord,
        ranked: list[dict[str, object]],
        linked_articles: list[KnowledgeArticle],
        worthiness: dict[str, object],
    ) -> dict[str, object]:
        default = self._deterministic_decision(ranked=ranked, worthiness=worthiness)
        if not self.llm_enabled:
            return default

        try:
            llm_decision = self._llm_decide_action(ticket=ticket, ranked=ranked, linked_articles=linked_articles)
        except Exception:
            return default
        if llm_decision is None:
            return default

        action = llm_decision["action"]
        confidence = llm_decision["confidence"]
        target_article = default["target_article"]
        top_score = int(ranked[0]["score"]) if ranked else 0

        if action in {KnowledgeProposedAction.update_existing, KnowledgeProposedAction.append_scenario}:
            if target_article is None or top_score < 18:
                action = KnowledgeProposedAction.needs_target_review
                target_article = None
        if action == KnowledgeProposedAction.not_recommended and bool(worthiness["recommended"]):
            action = default["action"]
            target_article = default["target_article"]
        if action == KnowledgeProposedAction.needs_target_review and not ranked:
            action = default["action"]
            target_article = default["target_article"]
        if action == KnowledgeProposedAction.needs_target_review and confidence < 0.55:
            action = default["action"]
            target_article = default["target_article"]

        return {
            "action": action,
            "confidence": confidence,
            "rationale": llm_decision["rationale"],
            "target_article": target_article,
        }

    def _deterministic_decision(
        self,
        *,
        ranked: list[dict[str, object]],
        worthiness: dict[str, object],
    ) -> dict[str, object]:
        if not bool(worthiness["recommended"]):
            return {
                "action": KnowledgeProposedAction.not_recommended,
                "confidence": 0.35,
                "rationale": str(worthiness["reason"]),
                "target_article": None,
            }

        if not ranked:
            return {
                "action": KnowledgeProposedAction.create_new,
                "confidence": 0.82,
                "rationale": (
                    "No strong existing article match was found, so a new article draft is the safest "
                    "recommendation."
                ),
                "target_article": None,
            }

        top = ranked[0]
        top_article = top["article"]
        top_score = int(top["score"])
        second_score = int(ranked[1]["score"]) if len(ranked) > 1 else 0
        reasons = "; ".join(str(item) for item in top.get("reasons", [])) or "best deterministic match"

        if len(ranked) > 1 and abs(top_score - second_score) <= 8 and top_score >= 18:
            return {
                "action": KnowledgeProposedAction.needs_target_review,
                "confidence": 0.46,
                "rationale": (
                    f"Multiple similar KB candidates were found ({reasons}); reviewer target "
                    "confirmation is safer."
                ),
                "target_article": top_article,
            }
        if top_score >= 65:
            return {
                "action": KnowledgeProposedAction.update_existing,
                "confidence": 0.88,
                "rationale": (
                    f"A strong existing KB match was found ({reasons}), so an article update is "
                    "recommended."
                ),
                "target_article": top_article,
            }
        if top_score >= 28:
            return {
                "action": KnowledgeProposedAction.append_scenario,
                "confidence": 0.71,
                "rationale": (
                    f"A related KB article exists ({reasons}), but the new case looks like an edge "
                    "case or scenario addendum."
                ),
                "target_article": top_article,
            }
        return {
            "action": KnowledgeProposedAction.create_new,
            "confidence": 0.61,
            "rationale": (
                "The best match is weak, so a new draft is safer than forcing an update into the "
                "wrong article."
            ),
            "target_article": None,
        }

    def _llm_decide_action(
        self,
        *,
        ticket: TicketRecord,
        ranked: list[dict[str, object]],
        linked_articles: list[KnowledgeArticle],
    ) -> dict[str, object] | None:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        candidate_lines = []
        for index, row in enumerate(ranked[:3], start=1):
            article = row["article"]
            candidate_lines.append(
                f"{index}. id={article.external_article_id}; title={article.title}; "
                f"score={row['score']}; summary={article.summary}"
            )
        linked_lines = [f"- {article.id}: {article.title}" for article in linked_articles]
        prompt = "\n".join(
            [
                "You are classifying a help desk knowledge base proposal.",
                "Decide whether this closed ticket should create a new article, update an existing article, append a new scenario, be marked not recommended, or require target review.",
                "Use only the supplied ticket and candidate article information.",
                "Do not invent a target article that is not listed.",
                "Return exactly one line in this format:",
                "action=<create_new|update_existing|append_scenario|not_recommended|needs_target_review>; confidence=<0.00-1.00>; rationale=<short reason>",
                f"Ticket subject: {ticket.subject}",
                f"Ticket tier: {ticket.tier.value}",
                f"Ticket priority: {ticket.priority.value}",
                f"Ticket type: {hidden.get('ticket_type', '-')}",
                f"Root cause: {hidden.get('root_cause', '-')}",
                f"Expected checks: {hidden.get('expected_agent_checks', [])}",
                "Linked scenario KB articles:",
                *(linked_lines or ["- none"]),
                "Candidate existing KB articles:",
                *(candidate_lines or ["- none"]),
            ]
        )
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
        }
        if self.engine_readiness is not None:
            self.engine_readiness.ensure_ready_for_llm()
        with httpx.Client(base_url=self.ollama_url, timeout=self.timeout_seconds) as client:
            response = client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        text = str(data.get("response", "")).strip()
        if not text:
            return None

        action_match = re.search(
            r"action\s*=\s*(create_new|update_existing|append_scenario|not_recommended|needs_target_review)",
            text,
            flags=re.IGNORECASE,
        )
        confidence_match = re.search(r"confidence\s*=\s*([0-9]*\.?[0-9]+)", text, flags=re.IGNORECASE)
        rationale_match = re.search(r"rationale\s*=\s*(.+)$", text, flags=re.IGNORECASE)
        if not action_match:
            return None
        action = KnowledgeProposedAction(action_match.group(1).lower())
        confidence = float(confidence_match.group(1)) if confidence_match else 0.5
        confidence = max(0.0, min(confidence, 1.0))
        rationale = rationale_match.group(1).strip() if rationale_match else "LLM classification returned no rationale."
        return {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
        }

    def _collect_contributing_ticket_ids(
        self,
        target_article: KnowledgeArticleCacheEntry | None,
    ) -> list[str]:
        if target_article is None:
            return []
        seen: set[str] = set()
        ticket_ids: list[str] = []
        for item in self.repository.list_kb_review_items(provider=self.provider_service.provider_name):
            external_id = item.published_external_article_id or item.target_external_article_id
            if external_id != target_article.external_article_id:
                continue
            if item.source_ticket_id not in seen:
                seen.add(item.source_ticket_id)
                ticket_ids.append(item.source_ticket_id)
            for ticket_id in item.contributing_ticket_ids:
                if ticket_id not in seen:
                    seen.add(ticket_id)
                    ticket_ids.append(ticket_id)
        return ticket_ids

    def _build_title(
        self,
        *,
        ticket: TicketRecord,
        target_article: KnowledgeArticleCacheEntry | None,
    ) -> str:
        if target_article is not None:
            return target_article.title
        return ticket.subject.strip() or "Untitled KB Proposal"

    def _build_summary(
        self,
        *,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        target_article: KnowledgeArticleCacheEntry | None,
    ) -> str:
        if target_article is not None and target_article.summary.strip():
            return target_article.summary.strip()
        customer_message = next(
            (row.body.strip() for row in interactions if row.actor == "customer" and row.body.strip()),
            "",
        )
        if customer_message:
            summary = " ".join(customer_message.split())
            return summary[:177] + "..." if len(summary) > 180 else summary
        return ticket.subject.strip()

    def _build_tags(
        self,
        *,
        ticket: TicketRecord,
        target_article: KnowledgeArticleCacheEntry | None,
    ) -> list[str]:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        persona = hidden.get("persona", {}) if isinstance(hidden.get("persona", {}), dict) else {}
        tags = {
            str(hidden.get("ticket_type", "")).strip().lower(),
            str(persona.get("role", "")).strip().lower(),
            ticket.tier.value,
        }
        for value in hidden.get("knowledge_article_ids", []):
            cleaned = str(value).strip().lower()
            if cleaned:
                tags.add(cleaned)
        if target_article is not None:
            for value in target_article.tags:
                cleaned = str(value).strip().lower()
                if cleaned:
                    tags.add(cleaned)
        return sorted(tag for tag in tags if tag)

    def _build_draft_body(
        self,
        *,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        article_type: KnowledgeArticleType,
        proposed_action: KnowledgeProposedAction,
        target_article: KnowledgeArticleCacheEntry | None,
        linked_articles: list[KnowledgeArticle],
        contributing_ticket_ids: list[str],
    ) -> str:
        if proposed_action in {KnowledgeProposedAction.update_existing, KnowledgeProposedAction.append_scenario} and target_article:
            return self._build_update_body(
                ticket=ticket,
                interactions=interactions,
                proposed_action=proposed_action,
                target_article=target_article,
                contributing_ticket_ids=contributing_ticket_ids,
            )
        return self._build_new_article_body(
            ticket=ticket,
            interactions=interactions,
            article_type=article_type,
            linked_articles=linked_articles,
            contributing_ticket_ids=contributing_ticket_ids,
        )

    def _build_new_article_body(
        self,
        *,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        article_type: KnowledgeArticleType,
        linked_articles: list[KnowledgeArticle],
        contributing_ticket_ids: list[str],
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        persona = hidden.get("persona", {}) if isinstance(hidden.get("persona", {}), dict) else {}
        customer_message = next(
            (row.body.strip() for row in interactions if row.actor == "customer" and row.body.strip()),
            ticket.subject,
        )
        checks = [str(item).strip() for item in hidden.get("expected_agent_checks", []) if str(item).strip()]
        steps = [str(item).strip() for item in hidden.get("resolution_steps", []) if str(item).strip()]
        root_cause = str(hidden.get("root_cause", "Root cause not documented.")).strip()
        related = [
            f"- {article.title} ({article.url})"
            for article in linked_articles
        ] or ["- None linked yet."]
        ticket_refs = [ticket.id, *contributing_ticket_ids]
        ticket_refs = [ref for index, ref in enumerate(ticket_refs) if ref and ref not in ticket_refs[:index]]
        if article_type == KnowledgeArticleType.how_to:
            return (
                f"## Purpose\nDocument the repeatable procedure for: {ticket.subject}.\n\n"
                "## When To Use\n"
                f"- Use this when the user reports: {customer_message}\n"
                f"- Department / role context: {persona.get('role', '-')}\n\n"
                "## Scope\n"
                f"- Tier: {ticket.tier.value}\n"
                f"- Priority profile: {ticket.priority.value}\n"
                f"- Ticket type: {hidden.get('ticket_type', '-')}\n\n"
                "## Required Access / Preconditions\n"
                f"{self._bullet_block(checks) or '- Confirm the request is approved and in scope.'}\n\n"
                "## Procedure\n"
                f"{self._bullet_block(steps) or '- Follow the approved operational procedure for this request.'}\n\n"
                "## Validation\n"
                "- Confirm the user can complete the original action.\n"
                "- Confirm no broader access than intended was granted.\n\n"
                "## Rollback / Cautions\n"
                "- Revert any temporary or excessive access if the request was applied incorrectly.\n"
                "- Document any exceptions before closing the ticket.\n\n"
                "## Escalation Criteria\n"
                "- Escalate if required permissions, tooling, or approvals are outside your scope.\n\n"
                "## Related Articles\n"
                f"{chr(10).join(related)}\n\n"
                "## Change History / Revision Note\n"
                f"- Initial proposal generated from ticket(s): {', '.join(ticket_refs)}.\n"
                f"- Confirmed root cause / procedural driver: {root_cause}\n"
            )
        return (
            f"## Purpose\nProvide repeatable troubleshooting guidance for: {ticket.subject}.\n\n"
            "## Symptoms / When To Use This\n"
            f"- Use this when the user reports: {customer_message}\n"
            f"- Department / role context: {persona.get('role', '-')}\n\n"
            "## Scope\n"
            f"- Tier: {ticket.tier.value}\n"
            f"- Priority profile: {ticket.priority.value}\n"
            f"- Ticket type: {hidden.get('ticket_type', '-')}\n\n"
            "## Required Access / Preconditions\n"
            "- Access to the relevant account, endpoint, or administrative tools.\n"
            "- Ability to validate the user's current access and recent changes.\n\n"
            "## Initial Validation\n"
            f"{self._bullet_block(checks[:3]) or '- Confirm the exact affected user, service, and current impact.'}\n\n"
            "## Troubleshooting Steps\n"
            f"{self._bullet_block(checks) or '- Follow the scenario-specific validation steps.'}\n\n"
            "## Root Cause\n"
            f"- {root_cause}\n\n"
            "## Resolution\n"
            f"{self._bullet_block(steps) or '- Apply the validated fix and document the change.'}\n\n"
            "## Validation / Post-Fix Checks\n"
            "- Confirm the user can complete the original task without error.\n"
            "- Confirm the final state is stable and policy-compliant.\n\n"
            "## Escalation Criteria\n"
            "- Escalate if the issue requires changes outside your access or ownership.\n\n"
            "## Related Articles\n"
            f"{chr(10).join(related)}\n\n"
            "## Change History / Revision Note\n"
            f"- Initial proposal generated from ticket(s): {', '.join(ticket_refs)}.\n"
            f"- Confirmed root cause: {root_cause}\n"
        )

    def _build_update_body(
        self,
        *,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        proposed_action: KnowledgeProposedAction,
        target_article: KnowledgeArticleCacheEntry,
        contributing_ticket_ids: list[str],
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        customer_message = next(
            (row.body.strip() for row in interactions if row.actor == "customer" and row.body.strip()),
            ticket.subject,
        )
        checks = [str(item).strip() for item in hidden.get("expected_agent_checks", []) if str(item).strip()]
        steps = [str(item).strip() for item in hidden.get("resolution_steps", []) if str(item).strip()]
        update_mode = "Expanded scenario coverage" if proposed_action == KnowledgeProposedAction.append_scenario else "Proposed article update"
        ticket_refs = [ticket.id, *contributing_ticket_ids]
        ticket_refs = [ref for index, ref in enumerate(ticket_refs) if ref and ref not in ticket_refs[:index]]
        return (
            f"{target_article.body_markdown.rstrip()}\n\n"
            "## Additional Scenario Notes\n"
            f"- {update_mode} based on ticket {ticket.id}: {customer_message}\n"
            f"{self._bullet_block([*checks[:2], *steps[:2]]) or '- Validate the same scope before applying the change again.'}\n\n"
            "## Change History / Revision Note\n"
            f"- Updated from ticket(s): {', '.join(ticket_refs)}.\n"
            f"- Proposed action: {proposed_action.value}\n"
            f"- Most recent confirmed root cause: {hidden.get('root_cause', '-')}\n"
        )

    def _build_diff_summary(
        self,
        *,
        ticket: TicketRecord,
        target_article: KnowledgeArticleCacheEntry | None,
        proposed_action: KnowledgeProposedAction,
        interactions: list[InteractionRecord],
    ) -> dict[str, object]:
        last_agent = next(
            (row.body.strip() for row in reversed(interactions) if row.actor == "agent" and row.body.strip()),
            "",
        )
        return {
            "proposed_action": proposed_action.value,
            "target_article_id": target_article.external_article_id if target_article else None,
            "change_type": "new_article" if target_article is None else "update_existing_article",
            "source_ticket_id": ticket.id,
            "latest_agent_context": last_agent,
        }

    def _rewrite_draft_with_llm(
        self,
        *,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        article_type: KnowledgeArticleType,
        proposed_action: KnowledgeProposedAction,
        title: str,
        summary: str,
        body_markdown: str,
        target_article: KnowledgeArticleCacheEntry | None,
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        transcript = [
            f"- {row.actor}: {row.body.strip()}"
            for row in interactions[-8:]
            if row.body.strip()
        ]
        prompt = "\n".join(
            [
                "You are writing an internal IT knowledge base article draft.",
                "You may improve wording and structure, but you must keep the technical truth intact.",
                "Do not invent systems, permissions, tools, or root causes.",
                "If this is an update, preserve the article's existing scope and tone.",
                "Return only the revised markdown article body.",
                f"Article type: {article_type.value}",
                f"Proposed action: {proposed_action.value}",
                f"Draft title: {title}",
                f"Draft summary: {summary}",
                f"Source ticket subject: {ticket.subject}",
                f"Root cause: {hidden.get('root_cause', '-')}",
                f"Expected checks: {hidden.get('expected_agent_checks', [])}",
                f"Resolution steps: {hidden.get('resolution_steps', [])}",
                "Recent ticket interactions:",
                *(transcript or ["- none"]),
                "Current target article body:" if target_article else "No existing target article.",
                *( [target_article.body_markdown] if target_article else [] ),
                "Draft to improve:",
                body_markdown,
            ]
        )
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
        }
        if self.engine_readiness is not None:
            self.engine_readiness.ensure_ready_for_llm()
        with httpx.Client(base_url=self.ollama_url, timeout=self.timeout_seconds) as client:
            response = client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        text = str(data.get("response", "")).strip()
        if not text:
            raise RuntimeError("Ollama returned an empty KB draft")
        return text

    @staticmethod
    def _bullet_block(items: list[str]) -> str:
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        return "\n".join(f"- {item}" for item in cleaned)

    @staticmethod
    def _status_for_action(action: KnowledgeProposedAction) -> KnowledgeReviewStatus:
        if action == KnowledgeProposedAction.needs_target_review:
            return KnowledgeReviewStatus.needs_target_review
        if action == KnowledgeProposedAction.not_recommended:
            return KnowledgeReviewStatus.draft
        return KnowledgeReviewStatus.needs_review

    @staticmethod
    def _proposal_summary(
        *,
        review_item_id: str,
        action: KnowledgeProposedAction,
        worthiness: dict[str, object],
        target_article: KnowledgeArticleCacheEntry | None,
    ) -> str:
        action_label = action.value.replace("_", " ")
        summary = (
            f"KB proposal {review_item_id[:8]} created. Recommended action: {action_label}. "
            f"KB worthiness score: {worthiness['score']}."
        )
        if target_article is not None:
            summary += f" Matched existing article: {target_article.title} ({target_article.external_article_id})."
        if not bool(worthiness["recommended"]):
            summary += " Publishing is not strongly recommended until a reviewer confirms the value."
        return summary
