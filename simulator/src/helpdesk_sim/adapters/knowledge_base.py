from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class KnowledgeBaseArticleDraft:
    article_type: str
    title: str
    summary: str
    body_markdown: str
    tags: list[str] = field(default_factory=list)
    external_category_id: str | None = None
    locale_id: str | None = None
    publish_mode: str = "internal"


@dataclass(slots=True)
class KnowledgeBaseArticleSnapshot:
    external_article_id: str
    external_kb_id: str
    external_category_id: str
    locale_id: str
    title: str
    summary: str
    body_markdown: str
    tags: list[str] = field(default_factory=list)
    status: str = "unknown"
    version_token: str = ""


class KnowledgeBaseProvider(Protocol):
    def validate_configuration(self) -> dict[str, Any]:
        ...

    def list_sources(self) -> list[dict[str, Any]]:
        ...

    def sync_index(self, source_id: str | None = None) -> list[KnowledgeBaseArticleSnapshot]:
        ...

    def get_article(self, source_id: str | None, external_article_id: str) -> KnowledgeBaseArticleSnapshot | None:
        ...

    def create_article(self, draft: KnowledgeBaseArticleDraft) -> dict[str, Any]:
        ...

    def update_article(self, external_article_id: str, draft: KnowledgeBaseArticleDraft) -> dict[str, Any]:
        ...

    def publish_article(self, external_article_id: str, publish_mode: str) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class DisabledKnowledgeBaseProvider:
    reason: str = "Knowledge base provider is not configured."

    def validate_configuration(self) -> dict[str, Any]:
        return {
            "provider": "disabled",
            "enabled": False,
            "ready": False,
            "reason": self.reason,
        }

    def list_sources(self) -> list[dict[str, Any]]:
        return []

    def sync_index(self, source_id: str | None = None) -> list[KnowledgeBaseArticleSnapshot]:
        return []

    def get_article(self, source_id: str | None, external_article_id: str) -> KnowledgeBaseArticleSnapshot | None:
        return None

    def create_article(self, draft: KnowledgeBaseArticleDraft) -> dict[str, Any]:
        raise RuntimeError(self.reason)

    def update_article(self, external_article_id: str, draft: KnowledgeBaseArticleDraft) -> dict[str, Any]:
        raise RuntimeError(self.reason)

    def publish_article(self, external_article_id: str, publish_mode: str) -> dict[str, Any]:
        raise RuntimeError(self.reason)
