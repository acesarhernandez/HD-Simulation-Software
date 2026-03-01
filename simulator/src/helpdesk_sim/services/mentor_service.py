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

    def _generate_llm_reply(
        self,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        analyst_message: str,
    ) -> str:
        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        recent = [
            f"- {row.actor}: {row.body.strip()}"
            for row in interactions[-8:]
            if row.body.strip()
        ]
        prompt = "\n".join(
            [
                "You are a senior IT support engineer responding to a junior analyst in an internal chat.",
                "Use the provided ticket facts. Do not invent systems, causes, or fixes.",
                "This is an internal escalation consult, so you may be more direct than the end-user simulation.",
                "Give concise, practical troubleshooting or resolution guidance.",
                "Keep it to 2 to 5 sentences. No greeting or signature.",
                f"Ticket subject: {ticket.subject}",
                f"Tier: {ticket.tier.value}",
                f"Priority: {ticket.priority.value}",
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
