from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from helpdesk_sim.domain.models import ScoreMode, TicketRecord
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.coaching_service import CoachingService
from helpdesk_sim.services.engine_control_client import EngineReadinessCoordinator
from helpdesk_sim.services.mentor_service import MentorService
from helpdesk_sim.utils import to_iso, utc_now


PHASES: list[dict[str, str]] = [
    {
        "key": "intake_ownership",
        "title": "Intake and Ownership",
        "focus": "Claim ownership, acknowledge user impact, set clean working state.",
    },
    {
        "key": "identity_security",
        "title": "Identity and Security Gate",
        "focus": "Verify requester identity and policy alignment before access/account actions.",
    },
    {
        "key": "impact_priority",
        "title": "Impact and Priority Framing",
        "focus": "Document business impact, scope, and SLA risk where applicable.",
    },
    {
        "key": "user_communication",
        "title": "User Communication Plan",
        "focus": "Ask narrow, answerable questions with professional tone.",
    },
    {
        "key": "internal_troubleshooting",
        "title": "Internal Troubleshooting Plan",
        "focus": "Run scenario-grounded checks before proposing closure.",
    },
    {
        "key": "least_privilege",
        "title": "Least Privilege Guardrail",
        "focus": "Prefer minimal access and policy-compliant changes over broad rights.",
    },
    {
        "key": "resolution_or_escalation",
        "title": "Resolution or Escalation",
        "focus": "Resolve with evidence or escalate with a complete handoff package.",
    },
    {
        "key": "documentation_rubric",
        "title": "Documentation Rubric",
        "focus": "Capture impact, troubleshooting, root cause, resolution, and validation.",
    },
    {
        "key": "closure_validation",
        "title": "Closure Validation and State Hygiene",
        "focus": "Validate user outcome and close with correct state/ownership hygiene.",
    },
    {
        "key": "replay_review",
        "title": "Replay Review",
        "focus": "Compare your path against ideal guidance and lock next-step improvements.",
    },
]


@dataclass(slots=True)
class GodModeService:
    repository: SimulatorRepository
    mentor_service: MentorService
    coaching_service: CoachingService
    llm_enabled: bool
    ollama_url: str
    ollama_model: str
    default_attempt_first: bool = True
    reveal_mode: str = "guided"
    timeout_seconds: float = 25.0
    engine_readiness: EngineReadinessCoordinator | None = None

    def list_phases(self) -> list[dict[str, str]]:
        return [dict(row) for row in PHASES]

    def start_ticket(self, ticket_id: str, attempt_first: bool | None = None) -> dict[str, object]:
        ticket = self._require_ticket(ticket_id)
        hidden, god = self._prepare_state(
            ticket=ticket,
            attempt_first=attempt_first,
            create_if_missing=True,
        )
        hidden["god_mode"] = god
        self.repository.update_ticket_hidden_truth(ticket.id, hidden)
        self.repository.add_interaction(
            ticket_id=ticket.id,
            actor="god",
            body="God mode walkthrough started for this ticket.",
            metadata={"event": "god_start"},
        )
        return self.get_walkthrough(ticket_id)

    def get_walkthrough(self, ticket_id: str) -> dict[str, object]:
        ticket = self._require_ticket(ticket_id)
        interactions = self.repository.list_interactions(ticket.id)
        _, god = self._prepare_state(
            ticket=ticket,
            attempt_first=None,
            create_if_missing=False,
        )

        phase_rows = self._build_phase_rows(ticket=ticket, interactions=interactions, god_state=god)
        started = bool(god.get("enabled"))
        current_phase = self._current_phase_key(phase_rows) if started else None
        attempt_first = bool(god.get("attempt_first", self.default_attempt_first))
        truth_revealed = bool(god.get("truth_revealed"))

        phase_guidance = None
        if started and current_phase:
            phase_guidance = self.mentor_service.request_phase_guidance(
                ticket=ticket,
                interactions=interactions,
                phase_key=current_phase,
                attempt_text="",
                attempt_first=attempt_first,
            )

        summary = "God mode is ready for this ticket."
        if not started:
            summary = "God mode has not started for this ticket. Start walkthrough to enable guided steps."
        elif current_phase:
            summary = f"Current guided phase: {current_phase.replace('_', ' ')}."
        else:
            summary = "All guided phases are complete. Use replay review to summarize learning outcomes."

        return {
            "ticket_id": ticket.id,
            "started": started,
            "attempt_first": attempt_first,
            "reveal_mode": str(god.get("reveal_mode") or self.reveal_mode),
            "truth_revealed": truth_revealed,
            "truth_revealed_at": god.get("truth_revealed_at"),
            "current_phase": current_phase,
            "phases": phase_rows,
            "phase_guidance": phase_guidance,
            "hidden_truth_preview": self._build_truth_preview(ticket, truth_revealed),
            "english_summary": summary,
        }

    def submit_attempt(self, ticket_id: str, phase_key: str, text: str) -> dict[str, object]:
        ticket = self._require_ticket(ticket_id)
        if phase_key not in self._phase_map():
            raise ValueError(f"unknown phase '{phase_key}'")

        hidden, god = self._prepare_state(
            ticket=ticket,
            attempt_first=None,
            create_if_missing=True,
        )
        phase_state = self._phase_state(god, phase_key)
        phase_state["attempt_count"] = int(phase_state.get("attempt_count", 0)) + 1
        phase_state["last_attempt_at"] = to_iso(utc_now())
        hidden["god_mode"] = god
        self.repository.update_ticket_hidden_truth(ticket.id, hidden)

        self.repository.add_interaction(
            ticket_id=ticket.id,
            actor="god_student",
            body=text.strip(),
            metadata={"event": "god_attempt", "phase_key": phase_key},
        )

        interactions = self.repository.list_interactions(ticket.id)
        guidance = self.mentor_service.request_phase_guidance(
            ticket=ticket,
            interactions=interactions,
            phase_key=phase_key,
            attempt_text=text,
            attempt_first=bool(god.get("attempt_first", self.default_attempt_first)),
        )
        ideal = str(guidance.get("mentor_reply", "")).strip()
        delta = self.coaching_service.build_replay_delta(text, ideal)
        gate = self._evaluate_gate(phase_key=phase_key, ticket=ticket, interactions=interactions, attempt_text=text)
        can_advance = (not gate["required"]) or gate["passed"]

        self.repository.add_interaction(
            ticket_id=ticket.id,
            actor="god",
            body=ideal or "Guidance generated.",
            metadata={
                "event": "god_feedback",
                "phase_key": phase_key,
                "ideal_guidance": ideal,
                "delta": delta,
            },
        )

        return {
            "ticket_id": ticket.id,
            "phase_key": phase_key,
            "can_advance": can_advance,
            "gate": gate,
            "guidance": guidance,
            "delta": delta,
            "english_summary": (
                "Attempt reviewed. You can advance this phase."
                if can_advance
                else "Attempt reviewed. Complete the gate requirements before advancing."
            ),
        }

    def advance_phase(
        self,
        ticket_id: str,
        phase_key: str,
        note: str = "",
        force: bool = False,
    ) -> dict[str, object]:
        ticket = self._require_ticket(ticket_id)
        if phase_key not in self._phase_map():
            raise ValueError(f"unknown phase '{phase_key}'")

        interactions = self.repository.list_interactions(ticket.id)
        gate = self._evaluate_gate(phase_key=phase_key, ticket=ticket, interactions=interactions)
        if gate["required"] and not gate["passed"] and not force:
            raise ValueError(
                "phase gate is not complete; submit an attempt or pass force=true to override"
            )

        hidden, god = self._prepare_state(
            ticket=ticket,
            attempt_first=None,
            create_if_missing=True,
        )
        phase_state = self._phase_state(god, phase_key)
        phase_state["status"] = "completed"
        phase_state["advanced_at"] = to_iso(utc_now())
        checkpoints = god.get("checkpoints_passed", [])
        if not isinstance(checkpoints, list):
            checkpoints = []
        if phase_key not in checkpoints:
            checkpoints.append(phase_key)
        god["checkpoints_passed"] = checkpoints
        hidden["god_mode"] = god
        self.repository.update_ticket_hidden_truth(ticket.id, hidden)

        self.repository.add_interaction(
            ticket_id=ticket.id,
            actor="god",
            body=note.strip() or f"Advanced phase: {phase_key}.",
            metadata={"event": "god_phase_advance", "phase_key": phase_key, "force": force},
        )

        walkthrough = self.get_walkthrough(ticket_id)
        return {
            "ticket_id": ticket.id,
            "phase_key": phase_key,
            "advanced": True,
            "forced": force,
            "walkthrough": walkthrough,
            "english_summary": f"Phase '{phase_key}' marked completed.",
        }

    def reveal_truth(self, ticket_id: str) -> dict[str, object]:
        ticket = self._require_ticket(ticket_id)
        hidden, god = self._prepare_state(
            ticket=ticket,
            attempt_first=None,
            create_if_missing=True,
        )
        god["truth_revealed"] = True
        god["truth_revealed_at"] = to_iso(utc_now())
        hidden["god_mode"] = god
        self.repository.update_ticket_hidden_truth(ticket.id, hidden)

        self.repository.add_interaction(
            ticket_id=ticket.id,
            actor="god",
            body="Full hidden truth was revealed for guided training.",
            metadata={"event": "god_reveal_truth"},
        )

        truth = {
            "root_cause": hidden.get("root_cause"),
            "expected_agent_checks": hidden.get("expected_agent_checks", []),
            "resolution_steps": hidden.get("resolution_steps", []),
            "acceptable_resolution_keywords": hidden.get("acceptable_resolution_keywords", []),
        }
        return {
            "ticket_id": ticket.id,
            "truth_revealed": True,
            "truth": truth,
            "english_summary": "Hidden truth revealed for this guided ticket.",
        }

    def generate_draft(
        self,
        ticket_id: str,
        draft_type: str,
        instruction: str = "",
    ) -> dict[str, object]:
        ticket = self._require_ticket(ticket_id)
        interactions = self.repository.list_interactions(ticket.id)
        deterministic = self._deterministic_draft(
            draft_type=draft_type,
            ticket=ticket,
            interactions=interactions,
            instruction=instruction,
        )

        draft = deterministic
        llm_used = False
        last_error = None
        if self.llm_enabled:
            try:
                draft = self._generate_llm_draft(
                    draft_type=draft_type,
                    ticket=ticket,
                    interactions=interactions,
                    instruction=instruction,
                    fallback_text=deterministic,
                )
                llm_used = True
            except Exception as exc:  # pragma: no cover - network failure path
                last_error = str(exc)

        self.repository.add_interaction(
            ticket_id=ticket.id,
            actor="god",
            body=draft,
            metadata={
                "event": "god_draft",
                "draft_type": draft_type,
                "llm_used": llm_used,
            },
        )
        return {
            "ticket_id": ticket.id,
            "draft_type": draft_type,
            "draft": draft,
            "llm_used": llm_used,
            "last_error": last_error,
            "english_summary": (
                "Draft generated with LLM guidance."
                if llm_used
                else "Draft generated from deterministic guidance."
            ),
        }

    def build_replay(self, ticket_id: str) -> dict[str, object]:
        ticket = self._require_ticket(ticket_id)
        interactions = self.repository.list_interactions(ticket.id)
        attempts = []
        scores: list[int] = []
        phase_map = self._phase_map()

        for phase in PHASES:
            phase_key = phase["key"]
            attempt_text = ""
            ideal_text = ""
            for row in interactions:
                metadata = row.metadata if isinstance(row.metadata, dict) else {}
                if metadata.get("phase_key") != phase_key:
                    continue
                if metadata.get("event") == "god_attempt":
                    attempt_text = row.body.strip()
                if metadata.get("event") == "god_feedback":
                    ideal_text = str(metadata.get("ideal_guidance") or row.body).strip()

            if not attempt_text and not ideal_text:
                continue

            delta = self.coaching_service.build_replay_delta(attempt_text, ideal_text)
            scores.append(int(delta.get("score", 0)))
            attempts.append(
                {
                    "phase_key": phase_key,
                    "phase_title": phase_map[phase_key]["title"],
                    "attempt_text": attempt_text,
                    "ideal_text": ideal_text,
                    "delta": delta,
                }
            )

        overall = round(sum(scores) / len(scores), 2) if scores else 0.0
        return {
            "ticket_id": ticket.id,
            "attempt_count": len(attempts),
            "overall_replay_score": overall,
            "attempts": attempts,
            "english_summary": (
                f"Replay review generated with overall score {overall}/100."
                if attempts
                else "No God mode attempts were recorded for replay yet."
            ),
        }

    def tag_score_payload(self, ticket: TicketRecord, score_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(score_payload or {})
        meta = payload.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        god = hidden.get("god_mode", {}) if isinstance(hidden, dict) else {}
        guided = bool(god.get("enabled")) if isinstance(god, dict) else False
        meta["score_mode"] = (
            ScoreMode.guided_training.value if guided else ScoreMode.practice.value
        )
        meta["god_mode_used"] = guided
        payload["meta"] = meta
        return payload

    def _deterministic_draft(
        self,
        draft_type: str,
        ticket: TicketRecord,
        interactions: list,
        instruction: str,
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        checks = hidden.get("expected_agent_checks", []) if isinstance(hidden, dict) else []
        steps = hidden.get("resolution_steps", []) if isinstance(hidden, dict) else []
        root_cause = str(hidden.get("root_cause", "")).strip()
        prompt_note = f"\nInstruction: {instruction.strip()}" if instruction.strip() else ""

        if draft_type == "public_reply":
            top_checks = ", ".join(str(item) for item in checks[:2]) or "the core validation checks"
            return (
                "Hi, thanks for the update. I am validating "
                f"{top_checks} now to confirm the exact cause. "
                "I will follow up with next steps as soon as I confirm the findings."
                f"{prompt_note}"
            )

        if draft_type == "internal_note":
            step_text = ", ".join(str(item) for item in steps[:3]) or "document next corrective actions"
            return (
                "Impact: user cannot complete business task tied to this ticket.\n"
                "Troubleshooting: validated core access/state checks and captured user symptom details.\n"
                f"Root cause: {root_cause or 'not yet confirmed'}.\n"
                f"Resolution: {step_text}.\n"
                "Validation: confirm user workflow is restored and capture final confirmation."
                f"{prompt_note}"
            )

        if draft_type == "escalation_handoff":
            checked = ", ".join(str(item) for item in checks[:3]) or "baseline validation checks"
            return (
                "Escalation summary:\n"
                f"- Impact: {ticket.subject}\n"
                f"- Checks completed: {checked}\n"
                f"- Likely blocker/root cause: {root_cause or 'needs higher-tier validation'}\n"
                "- Request to next owner: confirm root cause and apply the required admin-level fix.\n"
                "- SLA risk: monitor response timeline and update requester every step."
                f"{prompt_note}"
            )

        raise ValueError(f"unsupported draft type '{draft_type}'")

    def _generate_llm_draft(
        self,
        draft_type: str,
        ticket: TicketRecord,
        interactions: list,
        instruction: str,
        fallback_text: str,
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        recent = [
            f"- {row.actor}: {row.body.strip()}"
            for row in interactions[-8:]
            if row.body.strip()
        ]
        prompt = "\n".join(
            [
                "You are an IT service desk training coach.",
                "Generate practical draft text grounded only in the provided ticket facts.",
                "Do not invent systems, permissions, root causes, or policy exceptions.",
                "Respect least-privilege handling and safe operational practices.",
                "Keep text concise and usable in real ticket work.",
                f"Draft type: {draft_type}",
                f"Ticket subject: {ticket.subject}",
                f"Tier: {ticket.tier.value}",
                f"Priority: {ticket.priority.value}",
                f"Hidden root cause: {hidden.get('root_cause', 'not provided')}",
                f"Expected checks: {hidden.get('expected_agent_checks', [])}",
                f"Resolution steps: {hidden.get('resolution_steps', [])}",
                "Recent interactions:",
                *(recent or ["- No recent interactions recorded."]),
                f"Additional instruction: {instruction or 'none'}",
                f"Fallback example text: {fallback_text}",
                "Return only the final draft text.",
            ]
        )
        payload = {"model": self.ollama_model, "prompt": prompt, "stream": False}
        if self.engine_readiness is not None:
            self.engine_readiness.ensure_ready_for_llm()
        with httpx.Client(base_url=self.ollama_url, timeout=self.timeout_seconds) as client:
            response = client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        text = str(data.get("response", "")).strip()
        if not text:
            raise RuntimeError("LLM returned an empty God mode draft")
        return text

    def _build_phase_rows(
        self,
        ticket: TicketRecord,
        interactions: list,
        god_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        phase_state = god_state.get("phase_state", {})
        if not isinstance(phase_state, dict):
            phase_state = {}
        phase_map = self._phase_map()
        for phase in PHASES:
            key = phase["key"]
            state = phase_state.get(key, {})
            if not isinstance(state, dict):
                state = {}
            gate = self._evaluate_gate(phase_key=key, ticket=ticket, interactions=interactions)
            rows.append(
                {
                    "key": key,
                    "title": phase_map[key]["title"],
                    "focus": phase_map[key]["focus"],
                    "status": str(state.get("status") or "pending"),
                    "attempt_count": int(state.get("attempt_count", 0) or 0),
                    "last_attempt_at": state.get("last_attempt_at"),
                    "advanced_at": state.get("advanced_at"),
                    "gate": gate,
                }
            )
        return rows

    def _evaluate_gate(
        self,
        phase_key: str,
        ticket: TicketRecord,
        interactions: list,
        attempt_text: str = "",
    ) -> dict[str, Any]:
        text_parts = [attempt_text.strip().lower()] if attempt_text.strip() else []
        for row in interactions:
            if row.actor not in {"agent", "god_student"}:
                continue
            if row.body.strip():
                text_parts.append(row.body.strip().lower())
        searchable = "\n".join(text_parts)

        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        ticket_type = str(hidden.get("ticket_type", "")).lower()
        root_cause = str(hidden.get("root_cause", "")).lower()
        priority = ticket.priority.value.lower()

        if phase_key == "identity_security":
            required = True
            checks = [
                "verify",
                "confirm username",
                "employee id",
                "mfa",
                "security",
                "identity",
            ]
            passed = any(token in searchable for token in checks)
            reason = (
                "Identity/security evidence found."
                if passed
                else "Add identity/security verification before account or access actions."
            )
            return {"required": required, "passed": passed, "reason": reason}

        if phase_key == "impact_priority":
            required = priority in {"high", "critical"} or ticket.tier.value in {"tier2", "sysadmin"}
            if not required:
                return {
                    "required": False,
                    "passed": True,
                    "reason": "Impact framing is optional for this ticket severity.",
                }
            checks = ["impact", "scope", "blocked", "business", "users", "department", "outage"]
            passed = any(token in searchable for token in checks)
            reason = (
                "Business impact framing captured."
                if passed
                else "Capture impact, scope, and urgency for SLA-aware handling."
            )
            return {"required": required, "passed": passed, "reason": reason}

        if phase_key == "least_privilege":
            required = (
                ticket_type in {"access_request", "onboarding", "offboarding"}
                or "permission" in root_cause
                or "admin" in root_cause
            )
            if not required:
                return {
                    "required": False,
                    "passed": True,
                    "reason": "Least-privilege gate is informational for this scenario.",
                }
            checks = ["least privilege", "approved", "policy", "group", "minimal access"]
            passed = any(token in searchable for token in checks)
            reason = (
                "Least-privilege safeguards are documented."
                if passed
                else "Document a least-privilege approach before granting broad access."
            )
            return {"required": required, "passed": passed, "reason": reason}

        if phase_key == "resolution_or_escalation":
            required = True
            resolution_markers = ["resolved", "fixed", "applied", "completed", "validated"]
            escalate_markers = ["escalat", "handoff", "tier 2", "sysadmin", "blocked"]
            passed = any(token in searchable for token in resolution_markers) or any(
                token in searchable for token in escalate_markers
            )
            reason = (
                "Resolution or escalation path is documented."
                if passed
                else "Document either a verified resolution path or a complete escalation handoff."
            )
            return {"required": required, "passed": passed, "reason": reason}

        if phase_key == "documentation_rubric":
            required = True
            required_sections = ["impact", "troubleshooting", "root cause", "resolution"]
            passed = all(section in searchable for section in required_sections)
            reason = (
                "Core documentation sections are present."
                if passed
                else "Add explicit impact, troubleshooting, root cause, and resolution notes."
            )
            return {"required": required, "passed": passed, "reason": reason}

        if phase_key == "closure_validation":
            required = True
            customer_confirmed = any(
                row.actor == "customer"
                and any(token in row.body.lower() for token in ("resolved", "works", "working", "fixed"))
                for row in interactions
            )
            response_logged = any(
                token in searchable for token in ("confirm", "validated", "close", "resolved")
            )
            passed = ticket.status.value == "closed" or (customer_confirmed and response_logged)
            reason = (
                "Closure validation evidence is present."
                if passed
                else "Capture user validation and closure rationale before final close."
            )
            return {"required": required, "passed": passed, "reason": reason}

        return {"required": False, "passed": True, "reason": "No mandatory gate for this phase."}

    def _build_truth_preview(self, ticket: TicketRecord, revealed: bool) -> dict[str, Any]:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        if revealed:
            return {
                "revealed": True,
                "root_cause": hidden.get("root_cause", ""),
                "expected_agent_checks": hidden.get("expected_agent_checks", []),
                "resolution_steps": hidden.get("resolution_steps", []),
                "acceptable_resolution_keywords": hidden.get("acceptable_resolution_keywords", []),
            }
        return {
            "revealed": False,
            "ticket_type": hidden.get("ticket_type", ""),
            "clue_map": hidden.get("clue_map", {}),
            "note": "Root cause is hidden in guided mode until reveal is requested.",
        }

    def _prepare_state(
        self,
        ticket: TicketRecord,
        attempt_first: bool | None,
        create_if_missing: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        hidden = dict(ticket.hidden_truth or {})
        god = hidden.get("god_mode", {})
        if not isinstance(god, dict):
            god = {}

        if not god and not create_if_missing:
            return hidden, {}

        started_at = str(god.get("started_at") or to_iso(utc_now()))
        phase_state = god.get("phase_state", {})
        if not isinstance(phase_state, dict):
            phase_state = {}
        for phase in PHASES:
            key = phase["key"]
            current = phase_state.get(key, {})
            if not isinstance(current, dict):
                current = {}
            phase_state[key] = {
                "status": str(current.get("status") or "pending"),
                "attempt_count": int(current.get("attempt_count", 0) or 0),
                "last_attempt_at": current.get("last_attempt_at"),
                "advanced_at": current.get("advanced_at"),
            }

        resolved_attempt_first = (
            bool(attempt_first)
            if attempt_first is not None
            else bool(god.get("attempt_first", self.default_attempt_first))
        )

        checkpoints = god.get("checkpoints_passed", [])
        if not isinstance(checkpoints, list):
            checkpoints = []

        prepared = {
            "enabled": True,
            "started_at": started_at,
            "attempt_first": resolved_attempt_first,
            "reveal_mode": str(god.get("reveal_mode") or self.reveal_mode),
            "truth_revealed": bool(god.get("truth_revealed", False)),
            "truth_revealed_at": god.get("truth_revealed_at"),
            "phase_state": phase_state,
            "checkpoints_passed": checkpoints,
        }
        return hidden, prepared

    @staticmethod
    def _phase_state(god_state: dict[str, Any], phase_key: str) -> dict[str, Any]:
        phase_state = god_state.get("phase_state", {})
        if not isinstance(phase_state, dict):
            phase_state = {}
            god_state["phase_state"] = phase_state
        state = phase_state.get(phase_key, {})
        if not isinstance(state, dict):
            state = {}
        phase_state[phase_key] = state
        return state

    @staticmethod
    def _current_phase_key(phase_rows: list[dict[str, Any]]) -> str | None:
        for row in phase_rows:
            if str(row.get("status")) != "completed":
                return str(row.get("key"))
        return None

    @staticmethod
    def _phase_map() -> dict[str, dict[str, str]]:
        return {row["key"]: row for row in PHASES}

    def _require_ticket(self, ticket_id: str) -> TicketRecord:
        ticket = self.repository.get_ticket(ticket_id)
        if ticket is None:
            raise ValueError("ticket not found")
        return ticket
