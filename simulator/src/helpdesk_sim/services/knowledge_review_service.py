from __future__ import annotations

from dataclasses import dataclass

import httpx

from helpdesk_sim.domain.models import (
    KnowledgePublishMode,
    KnowledgeReviewDecisionRequest,
    KnowledgeReviewStatus,
    KnowledgeRevisionRequest,
)
from helpdesk_sim.services.engine_control_client import EngineReadinessCoordinator
from helpdesk_sim.services.knowledge_proposal_service import KnowledgeProposalService
from helpdesk_sim.services.knowledge_provider_service import KnowledgeProviderService
from helpdesk_sim.utils import utc_now


@dataclass(slots=True)
class KnowledgeReviewService:
    proposal_service: KnowledgeProposalService
    provider_service: KnowledgeProviderService
    llm_enabled: bool
    ollama_url: str
    ollama_model: str
    review_required: bool = True
    timeout_seconds: float = 25.0
    engine_readiness: EngineReadinessCoordinator | None = None

    @property
    def repository(self):
        return self.proposal_service.repository

    def list_review_items(
        self,
        *,
        status: KnowledgeReviewStatus | None = None,
        provider: str | None = None,
        source_ticket_id: str | None = None,
    ) -> dict[str, object]:
        items = self.repository.list_kb_review_items(
            status=status,
            provider=provider,
            source_ticket_id=source_ticket_id,
        )
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "count": len(items),
        }

    def get_review_detail(self, review_item_id: str) -> dict[str, object]:
        return self.proposal_service.get_review_detail(review_item_id)

    def revise_review_item(
        self,
        review_item_id: str,
        payload: KnowledgeRevisionRequest,
    ) -> dict[str, object]:
        review_item = self.repository.get_kb_review_item(review_item_id)
        if review_item is None:
            raise ValueError("KB review item not found")
        target_article = None
        if review_item.target_external_article_id:
            target_article = self.repository.get_kb_article_cache_by_external(
                review_item.provider,
                review_item.target_external_article_id,
            )

        llm_used = False
        last_error = None
        try:
            revised_body = (
                self._revise_with_llm(review_item=review_item, instruction=payload.instruction, target_article=target_article)
                if self.llm_enabled
                else self._revise_deterministically(review_item.body_markdown, payload.instruction)
            )
            llm_used = self.llm_enabled
        except Exception as exc:  # pragma: no cover - network failure path
            last_error = str(exc)
            revised_body = self._revise_deterministically(review_item.body_markdown, payload.instruction)
            llm_used = False

        diff_summary = {
            **review_item.diff_summary,
            "revision_instruction": payload.instruction,
            "revision_length_delta": len(revised_body) - len(review_item.body_markdown),
            "llm_used": llm_used,
        }
        revision = self.repository.add_kb_review_revision(
            review_item.id,
            instruction_text=payload.instruction,
            body_markdown=revised_body,
            diff_summary=diff_summary,
            llm_used=llm_used,
        )
        self.repository.update_kb_review_item(
            review_item.id,
            body_markdown=revised_body,
            diff_summary=diff_summary,
            status=KnowledgeReviewStatus.needs_review
            if review_item.status == KnowledgeReviewStatus.draft
            else review_item.status,
        )
        self.repository.add_kb_review_event(
            review_item.id,
            event_type="revised",
            actor="user",
            notes="KB proposal revised by reviewer instruction.",
            metadata={"instruction": payload.instruction, "llm_used": llm_used, "last_error": last_error},
        )
        detail = self.get_review_detail(review_item.id)
        detail["revision"] = revision.model_dump(mode="json")
        detail["llm_used"] = llm_used
        detail["last_error"] = last_error
        detail["english_summary"] = (
            "KB proposal revised with Ollama."
            if llm_used
            else "KB proposal revised with deterministic fallback."
        )
        return detail

    def approve_review_item(
        self,
        review_item_id: str,
        payload: KnowledgeReviewDecisionRequest,
    ) -> dict[str, object]:
        review_item = self.repository.get_kb_review_item(review_item_id)
        if review_item is None:
            raise ValueError("KB review item not found")
        if review_item.status == KnowledgeReviewStatus.published:
            raise ValueError("This KB proposal is already published")
        self.repository.update_kb_review_item(
            review_item.id,
            review_notes=payload.notes,
            status=KnowledgeReviewStatus.approved,
            approved_at=utc_now(),
        )
        self.repository.add_kb_review_event(
            review_item.id,
            event_type="approved",
            actor="user",
            notes=payload.notes or "KB proposal approved for publish.",
            metadata={},
        )
        detail = self.get_review_detail(review_item.id)
        detail["english_summary"] = f"KB proposal {review_item.id[:8]} approved."
        return detail

    def reject_review_item(
        self,
        review_item_id: str,
        payload: KnowledgeReviewDecisionRequest,
    ) -> dict[str, object]:
        review_item = self.repository.get_kb_review_item(review_item_id)
        if review_item is None:
            raise ValueError("KB review item not found")
        self.repository.update_kb_review_item(
            review_item.id,
            review_notes=payload.notes,
            status=KnowledgeReviewStatus.rejected,
        )
        self.repository.add_kb_review_event(
            review_item.id,
            event_type="rejected",
            actor="user",
            notes=payload.notes or "KB proposal rejected.",
            metadata={},
        )
        detail = self.get_review_detail(review_item.id)
        detail["english_summary"] = f"KB proposal {review_item.id[:8]} rejected."
        return detail

    def publish_review_item(self, review_item_id: str) -> dict[str, object]:
        review_item = self.repository.get_kb_review_item(review_item_id)
        if review_item is None:
            raise ValueError("KB review item not found")
        if self.review_required and review_item.status != KnowledgeReviewStatus.approved:
            raise ValueError("Approve this KB proposal before publishing it")
        if review_item.status == KnowledgeReviewStatus.published:
            raise ValueError("This KB proposal is already published")
        publish_mode = KnowledgePublishMode(
            getattr(self.provider_service.provider, "publish_mode", KnowledgePublishMode.internal.value)
        )
        result = self.provider_service.publish_review_item(
            review_item,
            publish_mode=publish_mode,
        )
        detail = self.get_review_detail(review_item.id)
        detail["publish_result"] = result
        detail["english_summary"] = result["english_summary"]
        return detail

    def _revise_with_llm(self, *, review_item, instruction: str, target_article) -> str:
        prompt = "\n".join(
            [
                "You are revising an internal IT knowledge base draft.",
                "Apply the reviewer's instruction while keeping the article technically accurate.",
                "Do not invent root causes, systems, or permissions.",
                "Do not silently broaden the article scope.",
                "Return only the revised markdown article body.",
                f"Proposal action: {review_item.proposed_action.value}",
                f"Article type: {review_item.article_type.value}",
                f"Title: {review_item.title}",
                f"Summary: {review_item.summary}",
                f"Reviewer instruction: {instruction}",
                "Current target article body:" if target_article else "No existing target article body was matched.",
                *([target_article.body_markdown] if target_article else []),
                "Current draft:",
                review_item.body_markdown,
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
        revised = str(data.get("response", "")).strip()
        if not revised:
            raise RuntimeError("Ollama returned an empty KB revision")
        return revised

    @staticmethod
    def _revise_deterministically(body_markdown: str, instruction: str) -> str:
        note = (
            "\n\n## Reviewer Revision Note\n"
            f"- Manual revision requested: {instruction}\n"
            "- Review the article content and adjust the sections above before publishing.\n"
        )
        return body_markdown.rstrip() + note
