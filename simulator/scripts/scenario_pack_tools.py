#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from helpdesk_sim.domain.models import ScenarioTemplate

SCRIPT_ROOT = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_ROOT.parent
DEFAULT_TEMPLATES_DIR = SIM_ROOT / "src" / "helpdesk_sim" / "templates"
DEFAULT_SCENARIOS_PATH = DEFAULT_TEMPLATES_DIR / "scenarios.yaml"

PACK_TEMPLATE: dict[str, Any] = {
    "scenario_pack": {
        "name": "example-pack-name",
        "description": "Paste new generated scenarios here before import.",
        "created_by": "chatgpt-or-human-author",
        "created_at": "2026-03-20",
    },
    "scenarios": [
        {
            "id": "t1_onboarding_teamsprep_missing_bundle",
            "title": "Onboarding: user can sign in but Teams is unavailable",
            "ticket_type": "onboarding",
            "tier": "tier1",
            "priority": "high",
            "tags": ["onboarding", "licensing"],
            "persona_roles": ["HR"],
            "knowledge_article_ids": ["kb_onboarding_license_assignment"],
            "customer_problem": "New employee can sign in to portal but Teams says no active license.",
            "root_cause": "Onboarding workflow skipped the M365_E3 bundle.",
            "expected_agent_checks": [
                "check account status",
                "check assigned license bundles",
                "check required groups",
            ],
            "resolution_steps": [
                "Assign M365_E3 bundle",
                "Validate baseline onboarding group membership",
                "Have user sign out and sign in",
            ],
            "acceptable_resolution_keywords": [
                "assign license",
                "bundle",
                "group membership",
                "sign out and sign in",
            ],
            "clue_map": {
                "scope": "Only Teams fails; account sign-in works.",
                "timing": "User started today and account was created this morning.",
            },
            "diagnostics": {
                "account": {
                    "is_enabled": True,
                    "is_locked": False,
                    "lockout_reason": None,
                    "last_password_change_days": 1,
                    "password_max_age_days": 90,
                },
                "password": {
                    "relevant": True,
                    "is_expired": False,
                    "must_change_at_next_logon": True,
                    "last_password_change_days": 1,
                    "password_max_age_days": 90,
                    "mfa_enrolled": True,
                },
                "license": {
                    "relevant": True,
                    "required_bundles": ["M365_E3"],
                    "assigned_bundles": ["Exchange_Plan1"],
                    "missing_bundles": ["M365_E3"],
                },
                "groups": {
                    "relevant": True,
                    "required_groups": ["new_hire_default_access"],
                    "current_groups": ["new_hire_default_access"],
                    "missing_groups": [],
                },
                "mailbox": {
                    "relevant": False,
                    "mailbox_identifier": "",
                    "access_via_group": None,
                    "has_access": True,
                    "auto_mapping_enabled": True,
                },
            },
            "hint_bank": {
                "nudge": "Account works; start with entitlement checks.",
                "guided_step": "Compare required onboarding bundle against assigned bundles.",
                "strong_hint": "Assign M365_E3 and verify sign-in refresh.",
            },
            "default_follow_up": "I can retry as soon as the changes are applied.",
        },
        {
            "id": "t1_shared_mailbox_marketing_newhire",
            "title": "Email issue: new coordinator cannot open shared mailbox",
            "ticket_type": "email_issue",
            "tier": "tier1",
            "priority": "normal",
            "tags": ["email", "shared_mailbox", "access"],
            "persona_roles": ["Marketing"],
            "knowledge_article_ids": ["kb_shared_mailbox_access"],
            "customer_problem": "User can sign in to Outlook but cannot open team shared mailbox.",
            "root_cause": "Required mailbox access group membership was not assigned.",
            "expected_agent_checks": [
                "check mailbox access group membership",
                "check mailbox delegated access",
                "check assigned productivity license",
            ],
            "resolution_steps": [
                "Add user to shared mailbox access group",
                "Confirm delegated mailbox access",
                "Restart Outlook session",
            ],
            "acceptable_resolution_keywords": [
                "mailbox access group",
                "delegated access",
                "restart outlook",
            ],
            "clue_map": {
                "scope": "Outlook login works; issue is only shared mailbox access.",
                "history": "Coordinator account was created recently.",
            },
            "diagnostics": {
                "mailbox": {
                    "relevant": True,
                    "mailbox_identifier": "marketing-shared@company.local",
                    "access_via_group": "marketing_shared_mailbox_access",
                    "has_access": False,
                    "auto_mapping_enabled": True,
                },
                "groups": {
                    "relevant": True,
                    "required_groups": ["marketing_shared_mailbox_access"],
                    "current_groups": ["marketing_standard_access"],
                    "missing_groups": ["marketing_shared_mailbox_access"],
                },
                "license": {
                    "relevant": True,
                    "required_bundles": ["M365_E3"],
                    "assigned_bundles": ["M365_E3"],
                    "missing_bundles": [],
                },
            },
            "hint_bank": {
                "nudge": "Focus on delegated mailbox access path.",
                "guided_step": "Check the exact mailbox access group used for this shared mailbox.",
                "strong_hint": "Add missing mailbox group membership and restart Outlook.",
            },
            "default_follow_up": "I can test the shared mailbox right away once access is updated.",
        },
    ],
}


class ValidationSummary:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.valid_scenarios: list[dict[str, Any]] = []

    @property
    def ok(self) -> bool:
        return not self.errors


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")
    with path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return payload


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(payload, stream, sort_keys=False, allow_unicode=False)


def validate_pack(
    pack_path: Path,
    scenarios_path: Path,
    require_unique_against_existing: bool = False,
) -> ValidationSummary:
    summary = ValidationSummary()
    pack_payload = load_yaml(pack_path)

    scenarios_raw = pack_payload.get("scenarios")
    if not isinstance(scenarios_raw, list):
        summary.errors.append("Pack must include a top-level 'scenarios' list.")
        return summary

    existing_payload = load_yaml(scenarios_path)
    existing_rows = existing_payload.get("scenarios", [])
    existing_ids = {
        str(row.get("id")).strip()
        for row in existing_rows
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }

    seen_pack_ids: set[str] = set()

    for index, raw in enumerate(scenarios_raw, start=1):
        label = f"Scenario #{index}"
        if not isinstance(raw, dict):
            summary.errors.append(f"{label}: scenario entry must be an object.")
            continue

        scenario_id = str(raw.get("id", "")).strip()
        if not scenario_id:
            summary.errors.append(f"{label}: 'id' is required.")
            continue
        if scenario_id in seen_pack_ids:
            summary.errors.append(f"{label} ({scenario_id}): duplicate id inside this pack.")
            continue
        seen_pack_ids.add(scenario_id)

        if scenario_id in existing_ids:
            if require_unique_against_existing:
                summary.errors.append(
                    f"{label} ({scenario_id}): id already exists in {scenarios_path.name}."
                )
            else:
                summary.warnings.append(
                    f"{label} ({scenario_id}): id already exists and will require --allow-overwrite on import."
                )

        try:
            model = ScenarioTemplate.model_validate(raw)
        except ValidationError as exc:
            summary.errors.append(f"{label} ({scenario_id}): {exc}")
            continue

        diag_errors, diag_warnings = validate_diagnostics(model.diagnostics, scenario_id)
        summary.errors.extend(diag_errors)
        summary.warnings.extend(diag_warnings)
        summary.valid_scenarios.append(model.model_dump(mode="json"))

    if not summary.valid_scenarios:
        summary.warnings.append("No valid scenarios found in pack.")

    return summary


def validate_diagnostics(diagnostics: dict[str, Any], scenario_id: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not diagnostics:
        warnings.append(
            f"{scenario_id}: no diagnostics override provided. Defaults will be inferred from root_cause/clue_map."
        )
        return errors, warnings

    if not isinstance(diagnostics, dict):
        errors.append(f"{scenario_id}: diagnostics must be an object.")
        return errors, warnings

    list_fields = {
        "license.required_bundles",
        "license.assigned_bundles",
        "license.missing_bundles",
        "groups.required_groups",
        "groups.current_groups",
        "groups.missing_groups",
    }
    bool_fields = {
        "account.is_enabled",
        "account.is_locked",
        "password.relevant",
        "password.is_expired",
        "password.must_change_at_next_logon",
        "password.mfa_enrolled",
        "license.relevant",
        "groups.relevant",
        "mailbox.relevant",
        "mailbox.has_access",
        "mailbox.auto_mapping_enabled",
    }

    for field_path in list_fields:
        value = _get_nested(diagnostics, field_path)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"{scenario_id}: {field_path} must be a list of strings.")

    for field_path in bool_fields:
        value = _get_nested(diagnostics, field_path)
        if value is None:
            continue
        if not isinstance(value, bool):
            errors.append(f"{scenario_id}: {field_path} must be true/false.")

    return errors, warnings


def import_pack(
    pack_path: Path,
    scenarios_path: Path,
    allow_overwrite: bool,
    dry_run: bool,
    write_backup: bool,
) -> tuple[int, int]:
    summary = validate_pack(
        pack_path=pack_path,
        scenarios_path=scenarios_path,
        require_unique_against_existing=not allow_overwrite,
    )
    _print_validation(summary)
    if not summary.ok:
        raise ValueError("Pack validation failed. Fix errors and try again.")

    current_payload = load_yaml(scenarios_path)
    current_rows = current_payload.get("scenarios", [])
    if not isinstance(current_rows, list):
        raise ValueError(f"{scenarios_path} has invalid format: 'scenarios' must be a list.")

    by_id: dict[str, dict[str, Any]] = {}
    for row in current_rows:
        if isinstance(row, dict):
            scenario_id = str(row.get("id", "")).strip()
            if scenario_id:
                by_id[scenario_id] = copy.deepcopy(row)

    inserted = 0
    updated = 0
    for row in summary.valid_scenarios:
        scenario_id = str(row["id"]).strip()
        if scenario_id in by_id:
            updated += 1
        else:
            inserted += 1
        by_id[scenario_id] = row

    merged_rows = sorted(by_id.values(), key=lambda row: str(row.get("id", "")))
    merged_payload = {"scenarios": merged_rows}

    if dry_run:
        return inserted, updated

    if write_backup:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = scenarios_path.with_suffix(f".yaml.bak-{timestamp}")
        backup_path.write_text(scenarios_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backup created: {backup_path}")

    save_yaml(scenarios_path, merged_payload)
    return inserted, updated


def write_template(output_path: Path) -> None:
    save_yaml(output_path, PACK_TEMPLATE)
    print(f"Template written: {output_path}")


def _print_validation(summary: ValidationSummary) -> None:
    if summary.errors:
        print("Validation errors:")
        for line in summary.errors:
            print(f"- {line}")
    if summary.warnings:
        print("Validation warnings:")
        for line in summary.warnings:
            print(f"- {line}")
    print(
        "Validation summary: "
        f"{len(summary.valid_scenarios)} valid, {len(summary.warnings)} warnings, {len(summary.errors)} errors."
    )


def _get_nested(payload: dict[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Template, validate, and import scenario packs into scenarios.yaml."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    template_parser = subparsers.add_parser("template", help="Write a starter scenario pack file.")
    template_parser.add_argument(
        "--output",
        type=Path,
        default=SIM_ROOT / "scenario-pack-template.yaml",
        help="Path to write the scenario pack template.",
    )

    validate_parser = subparsers.add_parser("validate", help="Validate a scenario pack file.")
    validate_parser.add_argument("--pack", type=Path, required=True, help="Scenario pack YAML path.")
    validate_parser.add_argument(
        "--scenarios",
        type=Path,
        default=DEFAULT_SCENARIOS_PATH,
        help="Target scenarios.yaml used for duplicate-id checks.",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Validate and merge a scenario pack into scenarios.yaml.",
    )
    import_parser.add_argument("--pack", type=Path, required=True, help="Scenario pack YAML path.")
    import_parser.add_argument(
        "--scenarios",
        type=Path,
        default=DEFAULT_SCENARIOS_PATH,
        help="Target scenarios.yaml to update.",
    )
    import_parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="Allow incoming scenarios to replace existing scenarios with the same id.",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report merge counts without writing changes.",
    )
    import_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a timestamped backup of scenarios.yaml before writing.",
    )

    args = parser.parse_args()

    try:
        if args.command == "template":
            write_template(args.output.resolve())
            return 0

        if args.command == "validate":
            summary = validate_pack(args.pack.resolve(), args.scenarios.resolve())
            _print_validation(summary)
            return 0 if summary.ok else 1

        if args.command == "import":
            inserted, updated = import_pack(
                pack_path=args.pack.resolve(),
                scenarios_path=args.scenarios.resolve(),
                allow_overwrite=bool(args.allow_overwrite),
                dry_run=bool(args.dry_run),
                write_backup=not bool(args.no_backup),
            )
            mode = "DRY RUN" if args.dry_run else "IMPORT COMPLETE"
            print(f"{mode}: inserted={inserted} updated={updated}")
            return 0
    except Exception as exc:
        print(f"scenario-pack-tools: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
