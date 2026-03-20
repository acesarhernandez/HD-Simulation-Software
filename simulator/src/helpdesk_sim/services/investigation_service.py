from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from helpdesk_sim.domain.models import TicketRecord
from helpdesk_sim.utils import to_iso, utc_now

_CHECK_LABELS: dict[str, str] = {
    "account_status": "Account Status",
    "password_status": "Password Policy",
    "license_assignment": "License Assignment",
    "group_membership": "Group Membership",
    "mailbox_access": "Mailbox Access",
}

_DEFAULT_CHECK_SEQUENCE: tuple[str, ...] = tuple(_CHECK_LABELS.keys())

_CATEGORY_PRIORITY: dict[str, tuple[str, ...]] = {
    "password_access": (
        "account_status",
        "password_status",
        "group_membership",
        "license_assignment",
        "mailbox_access",
    ),
    "onboarding": (
        "account_status",
        "license_assignment",
        "group_membership",
        "mailbox_access",
        "password_status",
    ),
    "email_issue": (
        "mailbox_access",
        "group_membership",
        "license_assignment",
        "account_status",
        "password_status",
    ),
    "general": _DEFAULT_CHECK_SEQUENCE,
}


def classify_console_category(ticket_type: str | None) -> str:
    normalized = str(ticket_type or "").strip().lower()
    if normalized in {"password_reset", "access_request", "access_issue"}:
        return "password_access"
    if normalized == "onboarding":
        return "onboarding"
    if normalized == "email_issue":
        return "email_issue"

    if "password" in normalized or "access" in normalized:
        return "password_access"
    if "onboard" in normalized:
        return "onboarding"
    if "mail" in normalized or "email" in normalized:
        return "email_issue"
    return "general"


def prioritized_checks(category: str) -> list[str]:
    ordered: list[str] = []
    configured = _CATEGORY_PRIORITY.get(category, _DEFAULT_CHECK_SEQUENCE)
    for check_id in configured:
        if check_id in _CHECK_LABELS and check_id not in ordered:
            ordered.append(check_id)
    for check_id in _DEFAULT_CHECK_SEQUENCE:
        if check_id not in ordered:
            ordered.append(check_id)
    return ordered


def build_diagnostics_snapshot(
    ticket_type: str | None,
    root_cause: str | None,
    clue_map: dict[str, Any] | None,
    department: str | None,
    tier: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = _build_default_diagnostics(
        ticket_type=ticket_type,
        root_cause=root_cause,
        clue_map=clue_map,
        department=department,
        tier=tier,
    )
    if not isinstance(overrides, dict) or not overrides:
        return snapshot

    return _apply_diagnostics_overrides(
        base=snapshot,
        overrides=overrides,
        department=department,
    )


@dataclass(slots=True)
class InvestigationService:
    def build_ticket_report(self, ticket: TicketRecord) -> dict[str, Any]:
        hidden = _as_dict(ticket.hidden_truth)
        persona = _as_dict(hidden.get("persona"))
        ticket_type = str(hidden.get("ticket_type") or "").strip()
        department = str(persona.get("role") or "").strip()

        configured_category = str(hidden.get("investigation_category") or "").strip().lower()
        category = (
            configured_category
            if configured_category in _CATEGORY_PRIORITY
            else classify_console_category(ticket_type)
        )
        order = prioritized_checks(category)

        diagnostics = build_diagnostics_snapshot(
            ticket_type=ticket_type,
            root_cause=str(hidden.get("root_cause") or "").strip(),
            clue_map=_as_dict(hidden.get("clue_map")),
            department=department,
            tier=ticket.tier.value,
            overrides=_as_dict(hidden.get("diagnostics")),
        )

        results: list[dict[str, Any]] = []
        for rank, check_id in enumerate(order, start=1):
            result = self._evaluate_check(check_id=check_id, diagnostics=diagnostics)
            result["check_id"] = check_id
            result["label"] = _CHECK_LABELS.get(check_id, check_id)
            result["priority_rank"] = rank
            results.append(result)

        return {
            "ticket_id": ticket.id,
            "console_category": category,
            "ticket_context": {
                "ticket_type": ticket_type or None,
                "tier": ticket.tier.value,
                "priority": ticket.priority.value,
                "status": ticket.status.value,
                "department": department or None,
                "scenario_id": ticket.scenario_id,
            },
            "prioritized_checks": [
                {
                    "check_id": check_id,
                    "label": _CHECK_LABELS.get(check_id, check_id),
                    "priority_rank": rank,
                }
                for rank, check_id in enumerate(order, start=1)
            ],
            "results": results,
            "diagnostics_source": "ticket_hidden_truth",
            "generated_at": to_iso(utc_now()),
        }

    def _evaluate_check(self, check_id: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
        if check_id == "account_status":
            return self._evaluate_account_status(diagnostics)
        if check_id == "password_status":
            return self._evaluate_password_status(diagnostics)
        if check_id == "license_assignment":
            return self._evaluate_license_assignment(diagnostics)
        if check_id == "group_membership":
            return self._evaluate_group_membership(diagnostics)
        if check_id == "mailbox_access":
            return self._evaluate_mailbox_access(diagnostics)

        return {
            "status": "not_applicable",
            "result_code": "unsupported_check",
            "fields": {},
        }

    def _evaluate_account_status(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        account = _as_dict(diagnostics.get("account"))
        is_enabled = _as_bool(account.get("is_enabled"), default=True)
        is_locked = _as_bool(account.get("is_locked"), default=False)

        status = "pass"
        code = "account_active"
        if not is_enabled:
            status = "fail"
            code = "account_disabled"
        elif is_locked:
            status = "fail"
            code = "account_locked"

        return {
            "status": status,
            "result_code": code,
            "fields": {
                "is_enabled": is_enabled,
                "is_locked": is_locked,
                "lockout_reason": account.get("lockout_reason"),
                "last_password_change_days": _as_int(
                    account.get("last_password_change_days"),
                    default=0,
                ),
                "password_max_age_days": _as_int(account.get("password_max_age_days"), default=90),
            },
        }

    def _evaluate_password_status(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        password = _as_dict(diagnostics.get("password"))
        relevant = _as_bool(password.get("relevant"), default=True)
        if not relevant:
            return {
                "status": "not_applicable",
                "result_code": "not_relevant",
                "fields": {},
            }

        expired = _as_bool(password.get("is_expired"), default=False)
        must_change = _as_bool(password.get("must_change_at_next_logon"), default=False)
        age_days = _as_int(password.get("last_password_change_days"), default=0)
        max_age_days = _as_int(password.get("password_max_age_days"), default=90)
        mfa_enrolled = _as_bool(password.get("mfa_enrolled"), default=True)

        status = "pass"
        code = "password_healthy"
        if expired:
            status = "fail"
            code = "password_expired"
        elif must_change:
            status = "warning"
            code = "password_change_required"
        elif age_days >= max_age_days:
            status = "warning"
            code = "password_near_or_over_policy_limit"

        return {
            "status": status,
            "result_code": code,
            "fields": {
                "is_expired": expired,
                "must_change_at_next_logon": must_change,
                "last_password_change_days": age_days,
                "password_max_age_days": max_age_days,
                "mfa_enrolled": mfa_enrolled,
            },
        }

    def _evaluate_license_assignment(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        license_data = _as_dict(diagnostics.get("license"))
        relevant = _as_bool(license_data.get("relevant"), default=False)
        required = _as_str_list(license_data.get("required_bundles"))
        assigned = _as_str_list(license_data.get("assigned_bundles"))
        missing = _as_str_list(license_data.get("missing_bundles"))

        if not missing and required:
            missing = [bundle for bundle in required if bundle not in assigned]

        if not relevant and not required:
            return {
                "status": "not_applicable",
                "result_code": "not_relevant",
                "fields": {
                    "required_bundles": required,
                    "assigned_bundles": assigned,
                    "missing_bundles": missing,
                },
            }

        if missing:
            status = "fail"
            code = "missing_license"
        else:
            status = "pass"
            code = "license_assigned"

        return {
            "status": status,
            "result_code": code,
            "fields": {
                "required_bundles": required,
                "assigned_bundles": assigned,
                "missing_bundles": missing,
            },
        }

    def _evaluate_group_membership(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        groups = _as_dict(diagnostics.get("groups"))
        relevant = _as_bool(groups.get("relevant"), default=False)
        required = _as_str_list(groups.get("required_groups"))
        current = _as_str_list(groups.get("current_groups"))
        missing = _as_str_list(groups.get("missing_groups"))

        if not missing and required:
            missing = [group for group in required if group not in current]

        if not relevant and not required:
            return {
                "status": "not_applicable",
                "result_code": "not_relevant",
                "fields": {
                    "required_groups": required,
                    "current_groups": current,
                    "missing_groups": missing,
                },
            }

        if missing:
            status = "fail"
            code = "missing_groups"
        else:
            status = "pass"
            code = "group_membership_ok"

        return {
            "status": status,
            "result_code": code,
            "fields": {
                "required_groups": required,
                "current_groups": current,
                "missing_groups": missing,
            },
        }

    def _evaluate_mailbox_access(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        mailbox = _as_dict(diagnostics.get("mailbox"))
        relevant = _as_bool(mailbox.get("relevant"), default=False)
        mailbox_identifier = str(mailbox.get("mailbox_identifier") or "").strip()

        if not relevant and not mailbox_identifier:
            return {
                "status": "not_applicable",
                "result_code": "not_relevant",
                "fields": {},
            }

        has_access = _as_bool(mailbox.get("has_access"), default=True)
        if has_access:
            status = "pass"
            code = "mailbox_access_ok"
        else:
            status = "fail"
            code = "mailbox_access_missing"

        return {
            "status": status,
            "result_code": code,
            "fields": {
                "mailbox_identifier": mailbox_identifier or None,
                "access_via_group": mailbox.get("access_via_group"),
                "has_access": has_access,
                "auto_mapping_enabled": _as_bool(mailbox.get("auto_mapping_enabled"), default=True),
            },
        }


def _build_default_diagnostics(
    ticket_type: str | None,
    root_cause: str | None,
    clue_map: dict[str, Any] | None,
    department: str | None,
    tier: str | None,
) -> dict[str, Any]:
    normalized_type = str(ticket_type or "").strip().lower()
    normalized_tier = str(tier or "").strip().lower()
    root = str(root_cause or "").strip().lower()
    clues = _as_dict(clue_map)
    clue_text = " ".join(str(value).lower() for value in clues.values())
    all_text = f"{normalized_type} {root} {clue_text}"
    category = classify_console_category(normalized_type)
    is_sysadmin = normalized_tier == "sysadmin"

    is_password_related = category == "password_access" or "password" in all_text
    is_onboarding = category == "onboarding"
    is_email_related = category == "email_issue" or "mailbox" in all_text or "outlook" in all_text

    account_disabled = any(token in all_text for token in ("deprovision", "disabled", "terminated"))
    account_locked = any(token in all_text for token in ("lockout", "locked", "too many attempts"))
    password_expired = "password expired" in all_text or ("expired" in all_text and "password" in all_text)
    if password_expired:
        password_age_days = 95
    elif is_password_related:
        password_age_days = 62
    else:
        password_age_days = 24

    password_max_age_days = 90

    license_relevant = is_onboarding or "license" in all_text or "licensed" in all_text
    if is_sysadmin and "license" not in all_text:
        license_relevant = False
    if "creative suite" in all_text:
        required_bundles = ["Creative_Cloud_All_Apps"]
    elif license_relevant:
        required_bundles = ["M365_E3"]
    else:
        required_bundles = []

    license_failure = any(
        token in all_text
        for token in (
            "not licensed",
            "missing license",
            "license assignment failed",
            "license pool consumed",
            "cannot activate",
        )
    )

    if license_failure or ("missing" in all_text and "license" in all_text):
        assigned_bundles = ["Exchange_Plan1"] if "teams" in all_text else []
    elif "creative suite" in all_text:
        assigned_bundles = []
    else:
        assigned_bundles = required_bundles.copy()
    missing_bundles = [bundle for bundle in required_bundles if bundle not in assigned_bundles]

    required_groups: list[str] = []
    normalized_department = str(department or "").strip().lower()
    if normalized_department:
        required_groups.append(f"{normalized_department.replace(' ', '_')}_standard_access")
    if "shared mailbox" in all_text:
        required_groups.append("hr_shared_mailbox_access")
    if "approver" in all_text:
        required_groups.append("finance_approver")
    if is_onboarding:
        required_groups.append("new_hire_default_access")
    if is_sysadmin and "incident" in all_text:
        required_groups.append("incident_response_team")
    required_groups = sorted(dict.fromkeys(required_groups))

    current_groups = [group for group in required_groups if "mailbox" not in group]
    if "group membership" in all_text or "missing" in all_text and "group" in all_text:
        current_groups = current_groups[:-1]
    missing_groups = [group for group in required_groups if group not in current_groups]

    mailbox_relevant = is_email_related or "shared mailbox" in all_text
    mailbox_identifier = "hr-shared@company.local" if "shared mailbox" in all_text else ""
    mailbox_has_access = not (
        "cannot open shared mailbox" in all_text
        or "missing shared mailbox permission" in all_text
        or "transport rule" in all_text
        or "outbox" in all_text
    )

    return {
        "account": {
            "is_enabled": not account_disabled,
            "is_locked": account_locked,
            "lockout_reason": "too_many_attempts" if account_locked else None,
            "last_password_change_days": password_age_days,
            "password_max_age_days": password_max_age_days,
        },
        "password": {
            "relevant": is_password_related or is_onboarding,
            "is_expired": password_expired,
            "must_change_at_next_logon": is_onboarding and not password_expired,
            "last_password_change_days": password_age_days,
            "password_max_age_days": password_max_age_days,
            "mfa_enrolled": "mfa" in all_text or is_password_related,
        },
        "license": {
            "relevant": license_relevant,
            "required_bundles": required_bundles,
            "assigned_bundles": assigned_bundles,
            "missing_bundles": missing_bundles,
        },
        "groups": {
            "relevant": bool(required_groups),
            "required_groups": required_groups,
            "current_groups": current_groups,
            "missing_groups": missing_groups,
        },
        "mailbox": {
            "relevant": mailbox_relevant,
            "mailbox_identifier": mailbox_identifier,
            "access_via_group": "hr_shared_mailbox_access" if mailbox_identifier else None,
            "has_access": mailbox_has_access,
            "auto_mapping_enabled": True,
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    keys = set(base.keys()) | set(override.keys())
    for key in keys:
        base_value = base.get(key)
        override_value = override.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge(base_value, override_value)
            continue
        if key in override:
            merged[key] = override_value
        else:
            merged[key] = base_value
    return merged


def _apply_diagnostics_overrides(
    base: dict[str, Any],
    overrides: dict[str, Any],
    department: str | None,
) -> dict[str, Any]:
    global_override = {k: v for k, v in overrides.items() if k != "by_department"}
    merged = _deep_merge(base, global_override) if global_override else dict(base)

    by_department = overrides.get("by_department")
    if not isinstance(by_department, dict):
        return merged

    normalized_department = str(department or "").strip().lower()
    if not normalized_department:
        return merged

    selected_override: dict[str, Any] | None = None
    for key, candidate in by_department.items():
        if not isinstance(candidate, dict):
            continue
        if str(key).strip().lower() == normalized_department:
            selected_override = candidate
            break

    if not selected_override:
        return merged

    return _deep_merge(merged, selected_override)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default
