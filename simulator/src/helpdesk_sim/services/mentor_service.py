from __future__ import annotations

from dataclasses import dataclass

import httpx

from helpdesk_sim.domain.models import InteractionRecord, TicketRecord


@dataclass(slots=True)
class MentorService:
    llm_enabled: bool
    ollama_url: str
    ollama_model: str
    timeout_seconds: float = 20.0

    def request_guidance(
        self,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        analyst_message: str,
    ) -> dict[str, object]:
        deterministic_reply = self._build_deterministic_reply(ticket, interactions, analyst_message)

        llm_reply = ""
        llm_used = False
        last_error = None
        if self.llm_enabled:
            try:
                llm_reply = self._generate_llm_reply(ticket, interactions, analyst_message)
                llm_used = bool(llm_reply)
            except Exception as exc:  # pragma: no cover - network failure path
                last_error = str(exc)

        return {
            "mentor_reply": llm_reply or deterministic_reply,
            "deterministic_reply": deterministic_reply,
            "llm_used": llm_used,
            "last_error": last_error,
            "english_summary": (
                "Mentor guidance generated with Ollama."
                if llm_used
                else "Mentor guidance generated from deterministic scenario data."
            ),
        }

    @staticmethod
    def _build_deterministic_reply(
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        analyst_message: str,
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        checks = [str(item).strip() for item in hidden.get("expected_agent_checks", []) if str(item).strip()]
        steps = [str(item).strip() for item in hidden.get("resolution_steps", []) if str(item).strip()]
        root_cause = str(hidden.get("root_cause", "")).strip()
        last_customer = next(
            (row.body.strip() for row in reversed(interactions) if row.actor == "customer" and row.body.strip()),
            "",
        )
        focus = MentorService._classify_guidance_focus(analyst_message)

        if focus == "communication":
            parts = [
                "Senior tech view:",
                "Keep the reply professional, direct, and easy for the user to answer.",
                f"Ask one or two narrow follow-up questions around: {', '.join(checks[:2]) or 'the next required validation points'}.",
                "Acknowledge the impact first, then ask for the exact detail you need instead of broad open-ended questions.",
            ]
            if last_customer:
                parts.append(f"Use the latest user detail to anchor your reply: {last_customer}")
            return " ".join(parts)

        if focus == "sla":
            parts = [
                "Senior tech view:",
                f"Treat this as a {ticket.priority.value} priority {ticket.tier.value} ticket and manage it against the configured SLA.",
                "Send a clear first response quickly, log every troubleshooting step, and escalate early if you are blocked on access, approvals, or systems outside your lane.",
                "Do not close the ticket until the user confirms the service is restored or you have a documented handoff.",
            ]
            if checks:
                parts.append(f"Before that, cover the core checks: {', '.join(checks[:3])}.")
            return " ".join(parts)

        if focus == "escalation":
            parts = [
                "Senior tech view:",
                "Escalate when your next action depends on permissions, tooling, or admin changes outside your scope.",
                f"When you hand it off, include the user impact, what you already checked ({', '.join(checks[:3]) or 'the expected checks'}), and the most likely blocker.",
            ]
            if root_cause:
                parts.append(f"Probable cause to mention in the handoff: {root_cause}")
            if steps:
                parts.append(f"The likely next owner will act on: {', '.join(steps[:2])}.")
            return " ".join(parts)

        if focus == "documentation":
            parts = [
                "Senior tech view:",
                "Your notes should clearly capture impact, scope, troubleshooting performed, findings, and the next action.",
                f"Document the checks you completed: {', '.join(checks[:3]) or 'the required validation steps'}.",
            ]
            if root_cause:
                parts.append(f"If confirmed, state the root cause plainly: {root_cause}")
            if steps:
                parts.append(f"Record the actual fix or next planned action: {', '.join(steps[:2])}.")
            return " ".join(parts)

        if focus == "triage":
            parts = [
                "Senior tech view:",
                "Triage this by confirming user impact, affected service, scope, urgency, and whether there is a workaround.",
                f"Your first checks should be: {', '.join(checks[:3]) or 'the scenario-specific validation steps'}.",
            ]
            if last_customer:
                parts.append(f"Current user-reported symptom: {last_customer}")
            return " ".join(parts)

        parts = [
            "Senior tech view:",
            f"Focus first on: {', '.join(checks[:3]) or 'the expected checks for this scenario'}.",
        ]
        if last_customer:
            parts.append(f"Latest user symptom: {last_customer}")
        if root_cause:
            parts.append(f"The likely technical cause is: {root_cause}")
        if steps:
            parts.append(f"Next corrective steps: {', '.join(steps[:3])}.")
        if analyst_message:
            parts.append("Use that to answer your internal question and move the ticket forward.")
        return " ".join(part for part in parts if part)

    @staticmethod
    def _classify_guidance_focus(analyst_message: str) -> str:
        text = analyst_message.lower()
        keyword_groups = (
            ("communication", ("communicat", "respond", "reply", "word", "phrase", "tone", "say to", "etiquette", "professional")),
            ("sla", ("sla", "service level", "response time", "resolution time", "breach", "deadline", "timer")),
            ("escalation", ("escalat", "handoff", "hand off", "transfer", "route", "higher tier", "sysadmin")),
            ("documentation", ("document", "note", "write-up", "write up", "summary", "kb", "knowledge article")),
            ("triage", ("triage", "priorit", "severity", "impact", "urgent", "queue")),
        )
        for focus, keywords in keyword_groups:
            if any(keyword in text for keyword in keywords):
                return focus
        return "technical"

    def _generate_llm_reply(
        self,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        analyst_message: str,
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        focus = self._classify_guidance_focus(analyst_message)
        recent = [
            f"- {row.actor}: {row.body.strip()}"
            for row in interactions[-8:]
            if row.body.strip()
        ]
        prompt = "\n".join(
            [
                "You are a senior IT support engineer responding to a junior analyst in an internal chat.",
                "Stay inside help desk operations only: troubleshooting, communication, SLA, escalation, documentation, triage, and best practices.",
                "Use the provided ticket facts. Do not invent systems, causes, or fixes.",
                "This is an internal escalation consult, so you may be more direct than the end-user simulation.",
                "Answer the analyst's actual question. Do not default back to troubleshooting if they are asking about communication, SLA, escalation, or notes.",
                "If the analyst asks for wording, provide concise wording they can actually use on the ticket.",
                "If the analyst asks about etiquette, keep the answer professional and practical.",
                "Keep it to 2 to 6 sentences or short bullet points. No greeting or signature.",
                f"Ticket subject: {ticket.subject}",
                f"Tier: {ticket.tier.value}",
                f"Priority: {ticket.priority.value}",
                f"Mentor focus: {focus}",
                f"Hidden root cause: {hidden.get('root_cause', 'not provided')}",
                f"Expected checks: {hidden.get('expected_agent_checks', [])}",
                f"Resolution steps: {hidden.get('resolution_steps', [])}",
                "Recent ticket interactions:",
                *(recent or ["- No recent interactions were captured."]),
                f"Analyst asks: {analyst_message}",
                "Reply with the mentor guidance only.",
            ]
        )
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
        }
        with httpx.Client(base_url=self.ollama_url, timeout=self.timeout_seconds) as client:
            response = client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        text = str(data.get("response", "")).strip()
        if not text:
            raise RuntimeError("Ollama returned an empty mentor reply")
        return text
