from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from helpdesk_sim.adapters.gateway import TicketArticle
from helpdesk_sim.domain.models import GeneratedTicket, TicketPriority, TicketTier


class ZammadHttpGateway:
    def __init__(
        self,
        base_url: str,
        token: str,
        verify_tls: bool = True,
        group_tier1: str = "Service Desk",
        group_tier2: str = "Tier 2",
        group_sysadmin: str = "Systems",
        customer_fallback_email: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_tls = verify_tls
        self.group_mapping: dict[TicketTier, str] = {
            TicketTier.tier1: group_tier1,
            TicketTier.tier2: group_tier2,
            TicketTier.sysadmin: group_sysadmin,
        }
        self.customer_fallback_email = customer_fallback_email.strip().lower()
        self._known_customers: set[str] = set()
        self._known_organizations: dict[str, int] = {}
        self._new_ticket_state_id_cache: int | None = None
        self._new_ticket_state_id_loaded = False
        self._closed_ticket_state_id_cache: int | None = None
        self._closed_ticket_state_id_loaded = False

    def create_ticket(self, ticket: GeneratedTicket) -> int:
        customer_email = self._resolve_customer_email(ticket)

        payload = {
            "title": ticket.subject,
            "group": self.group_mapping[ticket.tier],
            "customer": customer_email,
            "owner_id": 1,
            "state": "new",
            "priority": self._map_priority(ticket.priority),
            "article": {
                "subject": ticket.subject,
                "body": ticket.body,
                "type": "note",
                "internal": False,
                "sender": "Customer",
            },
        }
        new_state_id = self._new_ticket_state_id()
        if new_state_id is not None:
            payload["state_id"] = new_state_id
        data = self._request("POST", "/api/v1/tickets", json=payload)
        ticket_id = data.get("id")
        if ticket_id is None:
            raise RuntimeError("Zammad ticket creation did not return an id")
        return int(ticket_id)

    def _resolve_customer_email(self, ticket: GeneratedTicket) -> str:
        persona_email = ticket.customer_email.strip().lower()
        department = self._extract_customer_department(ticket)
        if department:
            department_customer_email = self._find_department_customer_email(department)
            if department_customer_email:
                self._known_customers.add(department_customer_email)
                return department_customer_email

        if persona_email:
            try:
                self._ensure_customer_exists(
                    ticket.customer_name,
                    persona_email,
                    department=department,
                )
                return persona_email
            except Exception as exc:
                if self.customer_fallback_email:
                    return self.customer_fallback_email
                raise RuntimeError(
                    "failed to resolve persona customer in Zammad "
                    "and no fallback email is configured"
                ) from exc

        if self.customer_fallback_email:
            return self.customer_fallback_email

        raise RuntimeError("ticket customer email is missing and no fallback email is configured")

    @staticmethod
    def _extract_customer_department(ticket: GeneratedTicket) -> str | None:
        hidden_truth = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        persona = hidden_truth.get("persona", {})
        if not isinstance(persona, dict):
            return None
        role = str(persona.get("role", "")).strip()
        return role or None

    def _find_department_customer_email(self, department: str) -> str | None:
        normalized = " ".join(department.strip().split())
        if not normalized:
            return None

        try:
            query = urllib.parse.quote_plus(normalized)
            data = self._request("GET", f"/api/v1/users/search?query={query}")
        except Exception:
            return None

        customer_role_id = self._customer_role_id()
        preferred: list[str] = []
        fallback: list[str] = []
        normalized_lower = normalized.lower()
        for row in self._extract_rows(data):
            email = str(row.get("email", "")).strip().lower()
            if not email:
                continue
            if row.get("active") is False:
                continue

            role_ids = row.get("role_ids")
            if customer_role_id is not None and isinstance(role_ids, list):
                normalized_roles = []
                for role_id in role_ids:
                    try:
                        normalized_roles.append(int(role_id))
                    except Exception:
                        continue
                if normalized_roles and customer_role_id not in normalized_roles:
                    continue

            org_text = str(
                row.get("organization")
                or row.get("organization_name")
                or row.get("department")
                or row.get("note")
                or ""
            ).strip().lower()
            if normalized_lower in org_text:
                preferred.append(email)
            else:
                fallback.append(email)

        if preferred:
            return preferred[0]
        if fallback:
            return fallback[0]
        return None

    def fetch_new_articles(self, zammad_ticket_id: int, after_article_id: int) -> list[TicketArticle]:
        data = self._request("GET", f"/api/v1/ticket_articles/by_ticket/{zammad_ticket_id}")
        articles: list[TicketArticle] = []
        if not isinstance(data, list):
            return articles
        for item in data:
            article_id = int(item.get("id", 0))
            if article_id <= after_article_id:
                continue
            body = str(item.get("body") or item.get("content") or "").strip()
            sender = str(item.get("sender") or item.get("from") or "unknown")
            internal = bool(item.get("internal", False))
            articles.append(
                TicketArticle(
                    id=article_id,
                    body=body,
                    sender=sender,
                    internal=internal,
                )
            )
        return sorted(articles, key=lambda article: article.id)

    def post_customer_reply(self, zammad_ticket_id: int, body: str, subject: str) -> None:
        payload = {
            "ticket_id": zammad_ticket_id,
            "subject": subject,
            "body": body,
            "type": "note",
            "internal": False,
            "sender": "Customer",
        }
        self._request("POST", "/api/v1/ticket_articles", json=payload)

    def is_ticket_closed(self, zammad_ticket_id: int) -> bool:
        data = self._request("GET", f"/api/v1/tickets/{zammad_ticket_id}")
        state_value = str(
            data.get("state")
            or data.get("state_name")
            or data.get("state_type")
            or ""
        ).lower()
        if state_value:
            return "closed" in state_value

        state_id = data.get("state_id")
        if state_id is None:
            return False

        state_meta = self._request("GET", f"/api/v1/ticket_states/{state_id}")
        state_type_name = str(
            state_meta.get("state_type")
            or state_meta.get("state_type_name")
            or state_meta.get("name")
            or ""
        ).lower()
        return "closed" in state_type_name

    def delete_ticket(self, zammad_ticket_id: int) -> bool:
        delete_paths = [
            f"/api/v1/tickets/{zammad_ticket_id}",
            f"/api/v1/tickets/{zammad_ticket_id}?force=true",
            f"/api/v1/ticket/{zammad_ticket_id}",
        ]
        last_error: Exception | None = None
        for path in delete_paths:
            try:
                self._request("DELETE", path)
                if self._is_ticket_missing(zammad_ticket_id):
                    return True
                last_error = RuntimeError(f"ticket {zammad_ticket_id} still exists after DELETE {path}")
            except Exception as exc:
                last_error = exc

        if self._is_ticket_missing(zammad_ticket_id):
            return True
        if last_error is not None:
            raise RuntimeError(f"failed to delete ticket {zammad_ticket_id}: {last_error}") from last_error
        return False

    def _is_ticket_missing(self, zammad_ticket_id: int) -> bool:
        try:
            self._request("GET", f"/api/v1/tickets/{zammad_ticket_id}")
            return False
        except Exception as exc:
            message = str(exc).lower()
            if "404" in message or "not found" in message or "no route matches" in message:
                return True
            raise

    def close_ticket(self, zammad_ticket_id: int) -> bool:
        payload: dict[str, Any] = {"state": "closed"}
        closed_state_id = self._closed_ticket_state_id()
        if closed_state_id is not None:
            payload["state_id"] = closed_state_id
        self._request("PUT", f"/api/v1/tickets/{zammad_ticket_id}", json=payload)
        return self.is_ticket_closed(zammad_ticket_id)

    def _new_ticket_state_id(self) -> int | None:
        if self._new_ticket_state_id_loaded:
            return self._new_ticket_state_id_cache
        self._new_ticket_state_id_loaded = True
        try:
            data = self._request("GET", "/api/v1/ticket_states")
        except Exception:
            return None

        for row in self._extract_rows(data):
            name = str(row.get("name", "")).strip().lower()
            state_type = str(
                row.get("state_type")
                or row.get("state_type_name")
                or ""
            ).strip().lower()
            if name == "new" or state_type == "new":
                state_id = row.get("id")
                if isinstance(state_id, int):
                    self._new_ticket_state_id_cache = state_id
                    return state_id
        return None

    def _closed_ticket_state_id(self) -> int | None:
        if self._closed_ticket_state_id_loaded:
            return self._closed_ticket_state_id_cache
        self._closed_ticket_state_id_loaded = True

        try:
            data = self._request("GET", "/api/v1/ticket_states")
        except Exception:
            return None

        for row in self._extract_rows(data):
            name = str(row.get("name", "")).strip().lower()
            state_type = str(
                row.get("state_type")
                or row.get("state_type_name")
                or ""
            ).strip().lower()
            if "closed" in name or "closed" in state_type:
                state_id = row.get("id")
                if isinstance(state_id, int):
                    self._closed_ticket_state_id_cache = state_id
                    return state_id
        return None

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        headers = {
            "Authorization": f"Token token={self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(base_url=self.base_url, verify=self.verify_tls, timeout=20.0) as client:
            response = client.request(method, path, headers=headers, json=json)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Zammad API {method} {path} failed with {response.status_code}: {response.text}"
                )
            if not response.content:
                return {}
            return response.json()

    def _ensure_customer_exists(
        self,
        full_name: str,
        email: str,
        department: str | None = None,
    ) -> None:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise RuntimeError("customer email is required")
        if normalized_email in self._known_customers:
            return

        search_failed = False
        query = urllib.parse.quote_plus(normalized_email)
        try:
            data = self._request("GET", f"/api/v1/users/search?query={query}")
            existing_user = self._find_user_in_search_result(data, normalized_email)
            if existing_user is not None:
                self._known_customers.add(normalized_email)
                if department:
                    user_id = existing_user.get("id")
                    if isinstance(user_id, int):
                        self._update_customer_department(user_id, department)
                return
        except Exception:
            search_failed = True

        first_name, last_name = self._split_name(full_name)
        payload: dict[str, Any] = {
            "firstname": first_name,
            "lastname": last_name,
            "email": normalized_email,
            "active": True,
        }
        if department:
            payload["note"] = f"Department: {department}"
            organization_id = self._ensure_organization_exists(department)
            if organization_id is not None:
                payload["organization_id"] = organization_id
                payload["organization"] = department

        customer_role_id = self._customer_role_id()
        if customer_role_id is not None:
            payload["role_ids"] = [customer_role_id]

        try:
            self._request("POST", "/api/v1/users", json=payload)
            self._known_customers.add(normalized_email)
        except Exception as exc:
            message = str(exc).lower()
            duplicate_markers = (
                "has already been taken",
                "already exists",
                "email address has already been taken",
            )
            if search_failed and any(marker in message for marker in duplicate_markers):
                self._known_customers.add(normalized_email)
                if department:
                    try:
                        retry = self._request("GET", f"/api/v1/users/search?query={query}")
                        existing_user = self._find_user_in_search_result(retry, normalized_email)
                        if existing_user is not None:
                            user_id = existing_user.get("id")
                            if isinstance(user_id, int):
                                self._update_customer_department(user_id, department)
                    except Exception:
                        pass
                return
            raise

    def _update_customer_department(self, user_id: int, department: str) -> None:
        normalized = " ".join(department.strip().split())
        if not normalized:
            return

        payload: dict[str, Any] = {"note": f"Department: {normalized}", "organization": normalized}
        organization_id = self._ensure_organization_exists(normalized)
        if organization_id is not None:
            payload["organization_id"] = organization_id
        try:
            self._request("PUT", f"/api/v1/users/{user_id}", json=payload)
        except Exception:
            # Best-effort metadata enrichment only.
            return

    def _ensure_organization_exists(self, department: str) -> int | None:
        normalized = " ".join(department.strip().split())
        if not normalized:
            return None

        cache_key = normalized.lower()
        if cache_key in self._known_organizations:
            return self._known_organizations[cache_key]

        try:
            query = urllib.parse.quote_plus(normalized)
            data = self._request("GET", f"/api/v1/organizations/search?query={query}")
            for row in self._extract_rows(data):
                if str(row.get("name", "")).strip().lower() != cache_key:
                    continue
                organization_id = row.get("id")
                if isinstance(organization_id, int):
                    self._known_organizations[cache_key] = organization_id
                    return organization_id
        except Exception:
            # Continue and attempt create when search API is restricted.
            pass

        created = self._request(
            "POST",
            "/api/v1/organizations",
            json={"name": normalized, "active": True},
        )
        organization_id = created.get("id")
        if isinstance(organization_id, int):
            self._known_organizations[cache_key] = organization_id
            return organization_id
        return None

    def _customer_role_id(self) -> int | None:
        data = self._request("GET", "/api/v1/roles")
        rows = self._extract_rows(data)
        for row in rows:
            if str(row.get("name", "")).strip().lower() == "customer":
                role_id = row.get("id")
                if isinstance(role_id, int):
                    return role_id
        return None

    @staticmethod
    def _user_exists_in_search_result(data: Any, email: str) -> bool:
        return ZammadHttpGateway._find_user_in_search_result(data, email) is not None

    @staticmethod
    def _find_user_in_search_result(data: Any, email: str) -> dict[str, Any] | None:
        rows = ZammadHttpGateway._extract_rows(data)
        for row in rows:
            row_email = str(row.get("email", "")).strip().lower()
            if row_email == email:
                return row
        return None

    @staticmethod
    def _extract_rows(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if not isinstance(data, dict):
            return []

        for key in ("data", "result", "roles", "users"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                return [row for row in value.values() if isinstance(row, dict)]

        assets = data.get("assets")
        if isinstance(assets, dict):
            collected: list[dict[str, Any]] = []
            for value in assets.values():
                if isinstance(value, dict):
                    collected.extend([row for row in value.values() if isinstance(row, dict)])
                elif isinstance(value, list):
                    collected.extend([row for row in value if isinstance(row, dict)])
            return collected

        return []

    @staticmethod
    def _split_name(full_name: str) -> tuple[str, str]:
        cleaned = " ".join(full_name.strip().split())
        if not cleaned:
            return ("Sim", "User")
        parts = cleaned.split(" ", 1)
        if len(parts) == 1:
            return (parts[0], "User")
        return (parts[0], parts[1])

    @staticmethod
    def _map_priority(priority: TicketPriority) -> str:
        mapping = {
            TicketPriority.low: "1 low",
            TicketPriority.normal: "2 normal",
            TicketPriority.high: "3 high",
            TicketPriority.critical: "4 urgent",
        }
        return mapping[priority]
