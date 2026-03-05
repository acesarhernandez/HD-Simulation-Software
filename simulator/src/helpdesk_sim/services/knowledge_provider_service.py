from __future__ import annotations

import hashlib
from dataclasses import dataclass

from helpdesk_sim.adapters.knowledge_base import (
    DisabledKnowledgeBaseProvider,
    KnowledgeBaseArticleDraft,
    KnowledgeBaseProvider,
)
from helpdesk_sim.domain.models import (
    KnowledgeArticleCacheEntry,
    KnowledgeProposedAction,
    KnowledgePublishMode,
    KnowledgeReviewItem,
    KnowledgeReviewStatus,
)
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.utils import utc_now


@dataclass(slots=True)
class KnowledgeProviderService:
    repository: SimulatorRepository
    provider: KnowledgeBaseProvider
    provider_name: str

    def is_enabled(self) -> bool:
        return not isinstance(self.provider, DisabledKnowledgeBaseProvider)

    def status(self) -> dict[str, object]:
        provider_status = self.provider.validate_configuration()
        cached = self.repository.list_kb_article_cache(self.provider_name) if self.is_enabled() else []
        last_sync = max((entry.last_synced_at for entry in cached), default=None)
        return {
            **provider_status,
            "cached_article_count": len(cached),
            "last_synced_at": last_sync.isoformat() if last_sync else None,
        }

    def sync_index(self) -> dict[str, object]:
        snapshots = self.provider.sync_index()
        entries: list[KnowledgeArticleCacheEntry] = []
        now = utc_now()
        for snapshot in snapshots:
            fingerprint = hashlib.sha256(
                f"{snapshot.title}\n{snapshot.summary}\n{snapshot.body_markdown}".encode("utf-8")
            ).hexdigest()
            entries.append(
                KnowledgeArticleCacheEntry(
                    id=f"{self.provider_name}:{snapshot.external_article_id}",
                    provider=self.provider_name,
                    external_article_id=snapshot.external_article_id,
                    external_kb_id=snapshot.external_kb_id,
                    external_category_id=snapshot.external_category_id,
                    locale_id=snapshot.locale_id,
                    title=snapshot.title,
                    summary=snapshot.summary,
                    body_markdown=snapshot.body_markdown,
                    tags=snapshot.tags,
                    status=snapshot.status,
                    fingerprint=fingerprint,
                    last_synced_at=now,
                    version_token=snapshot.version_token,
                )
            )

        replaced = self.repository.replace_kb_article_cache(self.provider_name, entries)
        return {
            "provider": self.provider_name,
            "cached_article_count": replaced,
            "last_synced_at": now.isoformat(),
            "english_summary": f"Synced {replaced} knowledge article(s) from {self.provider_name}.",
        }

    def publish_review_item(
        self,
        review_item: KnowledgeReviewItem,
        *,
        publish_mode: KnowledgePublishMode,
    ) -> dict[str, object]:
        draft = KnowledgeBaseArticleDraft(
            article_type=review_item.article_type.value,
            title=review_item.title,
            summary=review_item.summary,
            body_markdown=review_item.body_markdown,
            tags=review_item.tags,
            publish_mode=publish_mode.value,
        )

        if review_item.proposed_action in {
            KnowledgeProposedAction.create_new,
            KnowledgeProposedAction.not_recommended,
        }:
            result = self.provider.create_article(draft)
        else:
            target_id = review_item.target_external_article_id or review_item.published_external_article_id
            if not target_id:
                raise RuntimeError("No target external article is set for this KB update")
            result = self.provider.update_article(target_id, draft)

        published_id = str(result.get("external_article_id") or "")
        self.repository.update_kb_review_item(
            review_item.id,
            status=KnowledgeReviewStatus.published,
            published_at=utc_now(),
            published_external_article_id=published_id or None,
            publish_result=result,
        )
        self.repository.add_kb_review_event(
            review_item.id,
            event_type="published",
            actor="system",
            notes="KB proposal was published to the configured provider.",
            metadata=result,
        )
        # Refresh cached view after publish so future matches see the latest article state.
        try:
            self.sync_index()
        except Exception:
            pass
        return {
            "review_item_id": review_item.id,
            "published_external_article_id": published_id or None,
            "provider": self.provider_name,
            "publish_result": result,
            "english_summary": (
                f"Published KB proposal {review_item.id} to {self.provider_name} as article {published_id}."
                if published_id
                else f"Published KB proposal {review_item.id} to {self.provider_name}."
            ),
        }
