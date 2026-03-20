from datetime import timedelta

from helpdesk_sim.domain.models import TicketRecord
from helpdesk_sim.services.investigation_service import InvestigationService
from helpdesk_sim.utils import utc_now


def _ticket(hidden_truth: dict[str, object]) -> TicketRecord:
    now = utc_now()
    return TicketRecord(
        id="ticket-1",
        session_id="session-1",
        zammad_ticket_id=5001,
        subject="Investigation test",
        tier="tier1",
        priority="normal",
        status="open",
        scenario_id="scenario-test",
        hidden_truth=hidden_truth,
        created_at=now,
        updated_at=now,
        closed_at=now + timedelta(minutes=5),
        last_seen_article_id=0,
    )


def test_password_access_category_prioritizes_account_then_password() -> None:
    service = InvestigationService()
    ticket = _ticket(
        {
            "ticket_type": "password_reset",
            "diagnostics": {
                "account": {
                    "is_enabled": True,
                    "is_locked": True,
                    "lockout_reason": "too_many_attempts",
                    "last_password_change_days": 95,
                    "password_max_age_days": 90,
                },
                "password": {
                    "relevant": True,
                    "is_expired": True,
                    "must_change_at_next_logon": False,
                    "last_password_change_days": 95,
                    "password_max_age_days": 90,
                    "mfa_enrolled": True,
                },
            },
        }
    )

    report = service.build_ticket_report(ticket)

    assert report["console_category"] == "password_access"
    assert report["prioritized_checks"][0]["check_id"] == "account_status"
    assert report["prioritized_checks"][1]["check_id"] == "password_status"

    by_check = {row["check_id"]: row for row in report["results"]}
    assert by_check["account_status"]["status"] == "fail"
    assert by_check["account_status"]["result_code"] == "account_locked"
    assert by_check["password_status"]["status"] == "fail"
    assert by_check["password_status"]["result_code"] == "password_expired"


def test_onboarding_category_prioritizes_license_after_account() -> None:
    service = InvestigationService()
    ticket = _ticket(
        {
            "ticket_type": "onboarding",
            "diagnostics": {
                "license": {
                    "relevant": True,
                    "required_bundles": ["M365_E3"],
                    "assigned_bundles": ["Exchange_Plan1"],
                    "missing_bundles": ["M365_E3"],
                },
                "groups": {
                    "relevant": True,
                    "required_groups": ["new_hire_default_access"],
                    "current_groups": [],
                    "missing_groups": ["new_hire_default_access"],
                },
            },
        }
    )

    report = service.build_ticket_report(ticket)
    check_order = [row["check_id"] for row in report["prioritized_checks"]]

    assert report["console_category"] == "onboarding"
    assert check_order[:3] == ["account_status", "license_assignment", "group_membership"]

    by_check = {row["check_id"]: row for row in report["results"]}
    assert by_check["license_assignment"]["status"] == "fail"
    assert by_check["license_assignment"]["result_code"] == "missing_license"
    assert by_check["group_membership"]["status"] == "fail"
    assert by_check["group_membership"]["result_code"] == "missing_groups"


def test_email_issue_category_uses_ticket_hidden_truth_when_no_explicit_diagnostics() -> None:
    service = InvestigationService()
    ticket = _ticket(
        {
            "ticket_type": "email_issue",
            "root_cause": "Missing shared mailbox permission assignment in group membership.",
            "clue_map": {
                "account": "Can sign in to email and Teams, just not shared mailbox.",
            },
            "persona": {"role": "HR"},
        }
    )

    report = service.build_ticket_report(ticket)
    check_order = [row["check_id"] for row in report["prioritized_checks"]]

    assert report["console_category"] == "email_issue"
    assert check_order[:3] == ["mailbox_access", "group_membership", "license_assignment"]
    assert report["diagnostics_source"] == "ticket_hidden_truth"

    by_check = {row["check_id"]: row for row in report["results"]}
    assert by_check["mailbox_access"]["status"] == "fail"
    assert by_check["group_membership"]["status"] == "fail"


def test_department_specific_diagnostics_override_is_applied() -> None:
    service = InvestigationService()
    ticket = _ticket(
        {
            "ticket_type": "vpn_issue",
            "persona": {"role": "Finance"},
            "diagnostics": {
                "groups": {
                    "relevant": True,
                    "required_groups": ["sales_standard_access"],
                    "current_groups": ["sales_standard_access"],
                    "missing_groups": [],
                },
                "by_department": {
                    "Finance": {
                        "groups": {
                            "relevant": True,
                            "required_groups": ["finance_standard_access"],
                            "current_groups": ["finance_standard_access"],
                            "missing_groups": [],
                        }
                    }
                },
            },
        }
    )

    report = service.build_ticket_report(ticket)
    by_check = {row["check_id"]: row for row in report["results"]}
    group_fields = by_check["group_membership"]["fields"]
    assert group_fields["required_groups"] == ["finance_standard_access"]
