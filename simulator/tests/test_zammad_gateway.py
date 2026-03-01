from __future__ import annotations

import pytest

from helpdesk_sim.adapters.zammad_http_gateway import ZammadHttpGateway
from helpdesk_sim.domain.models import GeneratedTicket, TicketPriority, TicketTier


def _sample_ticket() -> GeneratedTicket:
    return GeneratedTicket(
        scenario_id="sample_scenario",
        session_id="sample_session",
        subject="Sample Subject",
        body="Sample body from persona.",
        tier=TicketTier.tier1,
        priority=TicketPriority.normal,
        customer_name="Melissa Brooks",
        customer_email="melissa.brooks@bmm.local",
        hidden_truth={"persona": {"role": "HR"}},
    )


def test_create_ticket_prefers_persona_customer_even_with_fallback() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="sim.test@bmm.local",
    )
    ticket = _sample_ticket()

    ensured: list[tuple[str, str, str | None]] = []
    created_payloads: list[dict[str, object]] = []

    def ensure_customer(full_name: str, email: str, department: str | None = None) -> None:
        ensured.append((full_name, email, department))

    def fake_request(
        method: str,
        path: str,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if method == "POST" and path == "/api/v1/tickets":
            created_payloads.append(json or {})
            return {"id": 101}
        raise AssertionError(f"unexpected request: {method} {path}")

    gateway._ensure_customer_exists = ensure_customer  # type: ignore[method-assign]
    gateway._request = fake_request  # type: ignore[method-assign]

    created_id = gateway.create_ticket(ticket)

    assert created_id == 101
    assert ensured == [("Melissa Brooks", "melissa.brooks@bmm.local", "HR")]
    assert created_payloads
    assert created_payloads[0]["customer"] == "melissa.brooks@bmm.local"


def test_fetch_new_articles_preserves_internal_flag() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="",
    )

    def fake_request(method: str, path: str, json: dict[str, object] | None = None) -> object:
        assert method == "GET"
        assert path == "/api/v1/ticket_articles/by_ticket/134"
        assert json is None
        return [
            {
                "id": 301,
                "body": "Public customer message",
                "sender": "Customer",
                "internal": False,
            },
            {
                "id": 303,
                "body": "Internal agent note",
                "sender": "Agent",
                "internal": True,
            },
            {
                "id": 304,
                "body": "Public agent reply",
                "sender": "Agent",
                "internal": False,
            },
        ]

    gateway._request = fake_request  # type: ignore[method-assign]

    articles = gateway.fetch_new_articles(134, after_article_id=0)

    assert [article.id for article in articles] == [301, 303, 304]
    assert articles[0].should_trigger_reply is False
    assert articles[1].should_trigger_reply is False
    assert articles[2].should_trigger_reply is True


def test_create_ticket_uses_fallback_when_persona_customer_resolution_fails() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="sim.test@bmm.local",
    )
    ticket = _sample_ticket()

    created_payloads: list[dict[str, object]] = []

    def ensure_customer(_full_name: str, _email: str, department: str | None = None) -> None:
        assert department == "HR"
        raise RuntimeError("cannot search users with current token")

    def fake_request(
        method: str,
        path: str,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if method == "POST" and path == "/api/v1/tickets":
            created_payloads.append(json or {})
            return {"id": 102}
        raise AssertionError(f"unexpected request: {method} {path}")

    gateway._ensure_customer_exists = ensure_customer  # type: ignore[method-assign]
    gateway._request = fake_request  # type: ignore[method-assign]

    created_id = gateway.create_ticket(ticket)

    assert created_id == 102
    assert created_payloads
    assert created_payloads[0]["customer"] == "sim.test@bmm.local"


def test_create_ticket_raises_without_fallback_when_persona_resolution_fails() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="",
    )
    ticket = _sample_ticket()

    def ensure_customer(_full_name: str, _email: str, _department: str | None = None) -> None:
        raise RuntimeError("cannot create user")

    def fake_request(
        _method: str,
        _path: str,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        raise AssertionError(
            "ticket create should not execute when customer "
            f"resolution fails: {json}"
        )

    gateway._ensure_customer_exists = ensure_customer  # type: ignore[method-assign]
    gateway._request = fake_request  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="no fallback email is configured"):
        gateway.create_ticket(ticket)


def test_ensure_customer_assigns_department_organization_when_creating_user() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="",
    )

    created_user_payloads: list[dict[str, object]] = []

    def fake_request(method: str, path: str, json: dict[str, object] | None = None) -> object:
        if method == "GET" and path.startswith("/api/v1/users/search?query="):
            return []
        if method == "GET" and path == "/api/v1/organizations/search?query=HR":
            return []
        if method == "POST" and path == "/api/v1/organizations":
            assert json == {"name": "HR", "active": True}
            return {"id": 44}
        if method == "GET" and path == "/api/v1/roles":
            return [{"id": 3, "name": "Customer"}]
        if method == "POST" and path == "/api/v1/users":
            created_user_payloads.append(json or {})
            return {"id": 501}
        raise AssertionError(f"unexpected request: {method} {path}")

    gateway._request = fake_request  # type: ignore[method-assign]
    gateway._ensure_customer_exists("Melissa Brooks", "melissa.brooks@bmm.local", department="HR")

    assert created_user_payloads
    payload = created_user_payloads[0]
    assert payload["email"] == "melissa.brooks@bmm.local"
    assert payload["organization_id"] == 44
    assert payload["role_ids"] == [3]
    assert payload["note"] == "Department: HR"


def test_create_ticket_prefers_existing_department_customer_before_template_persona() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="",
    )
    ticket = _sample_ticket()

    created_payloads: list[dict[str, object]] = []

    def fake_request(method: str, path: str, json: dict[str, object] | None = None) -> object:
        if method == "GET" and path == "/api/v1/users/search?query=HR":
            return [{"id": 77, "email": "emily.carter@bmm.local", "role_ids": [3], "organization": "HR"}]
        if method == "GET" and path == "/api/v1/roles":
            return [{"id": 3, "name": "Customer"}]
        if method == "POST" and path == "/api/v1/tickets":
            created_payloads.append(json or {})
            return {"id": 103}
        raise AssertionError(f"unexpected request: {method} {path}")

    def should_not_create_persona_user(
        _full_name: str,
        _email: str,
        _department: str | None = None,
    ) -> None:
        raise AssertionError("persona user creation should not run when a department customer exists")

    gateway._request = fake_request  # type: ignore[method-assign]
    gateway._ensure_customer_exists = should_not_create_persona_user  # type: ignore[method-assign]

    created_id = gateway.create_ticket(ticket)

    assert created_id == 103
    assert created_payloads
    assert created_payloads[0]["customer"] == "emily.carter@bmm.local"


def test_delete_ticket_calls_zammad_delete_endpoint() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="",
    )

    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, json: dict[str, object] | None = None) -> object:
        calls.append((method, path))
        assert json is None
        if method == "GET" and path == "/api/v1/tickets/66016":
            raise RuntimeError("Zammad API GET /api/v1/tickets/66016 failed with 404: not found")
        return {}

    gateway._request = fake_request  # type: ignore[method-assign]

    deleted = gateway.delete_ticket(66016)

    assert deleted is True
    assert calls == [
        ("DELETE", "/api/v1/tickets/66016"),
        ("GET", "/api/v1/tickets/66016"),
    ]


def test_create_ticket_sets_new_state_and_unassigned_owner_when_available() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="",
    )
    ticket = _sample_ticket()

    created_payloads: list[dict[str, object]] = []

    def fake_request(method: str, path: str, json: dict[str, object] | None = None) -> object:
        if method == "GET" and path == "/api/v1/ticket_states":
            return [{"id": 1, "name": "new"}]
        if method == "POST" and path == "/api/v1/tickets":
            created_payloads.append(json or {})
            return {"id": 104}
        raise AssertionError(f"unexpected request: {method} {path}")

    gateway._request = fake_request  # type: ignore[method-assign]
    gateway._resolve_customer_email = lambda _ticket: "melissa.brooks@bmm.local"  # type: ignore[method-assign]

    created_id = gateway.create_ticket(ticket)

    assert created_id == 104
    assert created_payloads
    payload = created_payloads[0]
    assert payload["owner_id"] == 1
    assert payload["state"] == "new"
    assert payload["state_id"] == 1


def test_close_ticket_calls_put_and_returns_true_when_closed() -> None:
    gateway = ZammadHttpGateway(
        base_url="http://zammad.local",
        token="token",
        customer_fallback_email="",
    )

    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, json: dict[str, object] | None = None) -> object:
        calls.append((method, path))
        if method == "GET" and path == "/api/v1/ticket_states":
            return [{"id": 4, "name": "closed", "state_type": "closed"}]
        if method == "PUT" and path == "/api/v1/tickets/66016":
            assert json is not None
            assert json.get("state") == "closed"
            assert json.get("state_id") == 4
            return {}
        if method == "GET" and path == "/api/v1/tickets/66016":
            return {"state": "closed"}
        raise AssertionError(f"unexpected request: {method} {path}")

    gateway._request = fake_request  # type: ignore[method-assign]

    closed = gateway.close_ticket(66016)

    assert closed is True
    assert calls == [
        ("GET", "/api/v1/ticket_states"),
        ("PUT", "/api/v1/tickets/66016"),
        ("GET", "/api/v1/tickets/66016"),
    ]
