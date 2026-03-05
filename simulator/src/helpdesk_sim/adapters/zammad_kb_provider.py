from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from helpdesk_sim.adapters.knowledge_base import (
    KnowledgeBaseArticleDraft,
    KnowledgeBaseArticleSnapshot,
)


@dataclass(slots=True)
class ZammadKnowledgeBaseProvider:
    base_url: str
    token: str
    knowledge_base_id: int
    locale_id: int
    default_category_id: int
    publish_mode: str = "internal"
    verify_tls: bool = True
    timeout_seconds: float = 20.0

    def validate_configuration(self) -> dict[str, Any]:
        if not self.token.strip():
            return {
                "provider": "zammad",
                "enabled": True,
                "ready": False,
                "reason": "Zammad token is not configured.",
            }
        if self.knowledge_base_id <= 0 or self.locale_id <= 0 or self.default_category_id <= 0:
            return {
                "provider": "zammad",
                "enabled": True,
                "ready": False,
                "reason": "KB ID, locale ID, and default category ID are required.",
            }
        try:
            kb = self._request("GET", f"/api/v1/knowledge_bases/{self.knowledge_base_id}")
        except Exception as exc:
            return {
                "provider": "zammad",
                "enabled": True,
                "ready": False,
                "reason": str(exc),
            }
        return {
            "provider": "zammad",
            "enabled": True,
            "ready": True,
            "knowledge_base_id": self.knowledge_base_id,
            "knowledge_base_name": kb.get("name") if isinstance(kb, dict) else "",
            "publish_mode": self.publish_mode,
        }

    def list_sources(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v1/knowledge_bases")
        if not isinstance(data, list):
            return []
        sources: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            sources.append(
                {
                    "id": str(row.get("id", "")),
                    "name": str(row.get("name", "")).strip(),
                    "active": bool(row.get("active", True)),
                }
            )
        return sources

    def sync_index(self, source_id: str | None = None) -> list[KnowledgeBaseArticleSnapshot]:
        kb_id = int(source_id or self.knowledge_base_id)
        data = self._request("POST", "/api/v1/knowledge_bases/init", json={"knowledge_base_id": kb_id})
        assets = data.get("assets", {}) if isinstance(data, dict) else {}
        return self._extract_snapshots_from_assets(assets=assets, kb_id=kb_id)

    def get_article(self, source_id: str | None, external_article_id: str) -> KnowledgeBaseArticleSnapshot | None:
        kb_id = int(source_id or self.knowledge_base_id)
        data = self._request("GET", f"/api/v1/knowledge_bases/{kb_id}/answers/{external_article_id}")
        if not isinstance(data, dict):
            return None

        title = ""
        body = ""
        summary = ""
        locale_id = str(self.locale_id)
        tags = self._extract_tags(data)
        translations = data.get("translations")
        if isinstance(translations, list):
            for row in translations:
                if not isinstance(row, dict):
                    continue
                row_locale = str(row.get("locale_id") or "")
                if row_locale and row_locale != locale_id:
                    continue
                title = str(row.get("title") or "").strip()
                body = str(row.get("content") or row.get("body") or "").strip()
                summary = self._summarize_body(body)
                locale_id = row_locale or locale_id
                break

        if not body:
            body = str(data.get("content") or data.get("body") or "").strip()
            summary = self._summarize_body(body)
        if not title:
            title = str(data.get("title") or "Untitled KB Article").strip()

        return KnowledgeBaseArticleSnapshot(
            external_article_id=str(data.get("id") or external_article_id),
            external_kb_id=str(kb_id),
            external_category_id=str(data.get("category_id") or self.default_category_id),
            locale_id=locale_id,
            title=title,
            summary=summary,
            body_markdown=body,
            tags=tags,
            status="published" if not bool(data.get("internal", True)) else "internal",
            version_token=str(data.get("updated_at") or data.get("id") or ""),
        )

    def create_article(self, draft: KnowledgeBaseArticleDraft) -> dict[str, Any]:
        payload = {
            "category_id": int(draft.external_category_id or self.default_category_id),
            "internal": self._publish_mode_to_internal(draft.publish_mode),
            "translations": [
                {
                    "locale_id": int(draft.locale_id or self.locale_id),
                    "title": draft.title,
                    "content": draft.body_markdown,
                }
            ],
        }
        data = self._request(
            "POST",
            f"/api/v1/knowledge_bases/{self.knowledge_base_id}/answers",
            json=payload,
        )
        if not isinstance(data, dict):
            raise RuntimeError("Zammad KB create did not return an article payload")
        return {
            "external_article_id": str(data.get("id", "")),
            "provider": "zammad",
            "result": data,
        }

    def update_article(self, external_article_id: str, draft: KnowledgeBaseArticleDraft) -> dict[str, Any]:
        payload = {
            "category_id": int(draft.external_category_id or self.default_category_id),
            "internal": self._publish_mode_to_internal(draft.publish_mode),
            "translations": [
                {
                    "locale_id": int(draft.locale_id or self.locale_id),
                    "title": draft.title,
                    "content": draft.body_markdown,
                }
            ],
        }
        data = self._request(
            "PUT",
            f"/api/v1/knowledge_bases/{self.knowledge_base_id}/answers/{external_article_id}",
            json=payload,
        )
        if not isinstance(data, dict):
            raise RuntimeError("Zammad KB update did not return an article payload")
        return {
            "external_article_id": str(data.get("id", external_article_id)),
            "provider": "zammad",
            "result": data,
        }

    def publish_article(self, external_article_id: str, publish_mode: str) -> dict[str, Any]:
        payload = {"internal": self._publish_mode_to_internal(publish_mode)}
        data = self._request(
            "PUT",
            f"/api/v1/knowledge_bases/{self.knowledge_base_id}/answers/{external_article_id}",
            json=payload,
        )
        if not isinstance(data, dict):
            raise RuntimeError("Zammad KB publish did not return an article payload")
        return {
            "external_article_id": str(data.get("id", external_article_id)),
            "provider": "zammad",
            "result": data,
        }

    def _extract_snapshots_from_assets(
        self,
        assets: dict[str, Any],
        kb_id: int,
    ) -> list[KnowledgeBaseArticleSnapshot]:
        if not isinstance(assets, dict):
            return []

        answers = self._asset_bucket(assets, "answer")
        translations = self._asset_bucket(assets, "translation")
        contents = self._asset_bucket(assets, "content")

        normalized_translations = {str(key): value for key, value in translations.items() if isinstance(value, dict)}
        normalized_contents = {str(key): value for key, value in contents.items() if isinstance(value, dict)}

        snapshots: list[KnowledgeBaseArticleSnapshot] = []
        for key, row in answers.items():
            if not isinstance(row, dict):
                continue
            translation_id = ""
            translation_ids = row.get("translation_ids")
            if isinstance(translation_ids, list) and translation_ids:
                translation_id = str(translation_ids[0])
            translation = normalized_translations.get(translation_id, {})

            content = {}
            content_ids = translation.get("content_ids")
            if isinstance(content_ids, list) and content_ids:
                content = normalized_contents.get(str(content_ids[0]), {})
            title = str(translation.get("title") or row.get("title") or "").strip() or "Untitled KB Article"
            body = str(
                content.get("body")
                or content.get("content")
                or translation.get("content")
                or row.get("body")
                or ""
            ).strip()
            snapshots.append(
                KnowledgeBaseArticleSnapshot(
                    external_article_id=str(row.get("id") or key),
                    external_kb_id=str(kb_id),
                    external_category_id=str(row.get("category_id") or self.default_category_id),
                    locale_id=str(translation.get("locale_id") or self.locale_id),
                    title=title,
                    summary=self._summarize_body(body),
                    body_markdown=body,
                    tags=self._extract_tags(row),
                    status="published" if not bool(row.get("internal", True)) else "internal",
                    version_token=str(row.get("updated_at") or row.get("id") or key),
                )
            )
        return snapshots

    @staticmethod
    def _asset_bucket(assets: dict[str, Any], marker: str) -> dict[str, Any]:
        for key, value in assets.items():
            if marker in str(key).lower() and isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _extract_tags(payload: dict[str, Any]) -> list[str]:
        raw = payload.get("tags") or payload.get("tag_list") or []
        if isinstance(raw, str):
            return [item.strip() for item in raw.split(",") if item.strip()]
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return []

    @staticmethod
    def _summarize_body(body: str, limit: int = 180) -> str:
        clean = " ".join(body.split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3].rstrip() + "..."

    @staticmethod
    def _publish_mode_to_internal(mode: str) -> bool:
        normalized = str(mode or "").strip().lower()
        return normalized != "public"

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        headers = {
            "Authorization": f"Token token={self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(base_url=self.base_url.rstrip("/"), verify=self.verify_tls, timeout=self.timeout_seconds) as client:
            response = client.request(method, path, headers=headers, json=json)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Zammad KB API {method} {path} failed with {response.status_code}: {response.text}"
                )
            if not response.content:
                return {}
            return response.json()
