from __future__ import annotations

from dataclasses import dataclass

import httpx

from helpdesk_sim.domain.models import InteractionRecord, TicketRecord


@dataclass(slots=True)
class CoachingService:
    llm_enabled: bool
    ollama_url: str
    ollama_model: str
    timeout_seconds: float = 20.0

    def generate_ticket_coaching(
        self,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
    ) -> dict[str, object]:
        score_payload = ticket.score if isinstance(ticket.score, dict) else {}
        score_detail = score_payload.get("score", {}) if isinstance(score_payload.get("score", {}), dict) else {}
        metrics = score_payload.get("metrics", {}) if isinstance(score_payload.get("metrics", {}), dict) else {}
        missed_checks = score_payload.get("missed_checks", [])
        if not isinstance(missed_checks, list):
            missed_checks = []

        strengths = self._build_strengths(score_detail)
        focus_areas = self._build_focus_areas(score_detail, missed_checks)
        documentation_critique = self._build_documentation_critique(interactions)
        professionalism_critique = self._build_professionalism_critique(interactions)
        deterministic_note = self._build_deterministic_note(
            ticket=ticket,
            score_detail=score_detail,
            metrics=metrics,
            strengths=strengths,
            focus_areas=focus_areas,
            documentation_critique=documentation_critique,
            professionalism_critique=professionalism_critique,
        )

        llm_note = ""
        llm_used = False
        last_error = None
        if self.llm_enabled:
            try:
                llm_note = self._generate_llm_note(
                    ticket=ticket,
                    score_detail=score_detail,
                    metrics=metrics,
                    strengths=strengths,
                    focus_areas=focus_areas,
                    documentation_critique=documentation_critique,
                    professionalism_critique=professionalism_critique,
                )
                llm_used = bool(llm_note)
            except Exception as exc:  # pragma: no cover - network failure path
                last_error = str(exc)

        return {
            "coaching_note": llm_note or deterministic_note,
            "deterministic_note": deterministic_note,
            "strengths": strengths,
            "focus_areas": focus_areas,
            "documentation_critique": documentation_critique,
            "professionalism_critique": professionalism_critique,
            "llm_used": llm_used,
            "last_error": last_error,
            "english_summary": (
                "Coaching note generated with Ollama."
                if llm_used
                else "Coaching note generated from deterministic grading data."
            ),
        }

    @staticmethod
    def _build_strengths(score_detail: dict[str, object]) -> list[str]:
        strengths: list[str] = []
        if int(score_detail.get("communication", 0) or 0) >= 10:
            strengths.append("Your communication stayed clear and professional.")
        if int(score_detail.get("troubleshooting", 0) or 0) >= 18:
            strengths.append("You covered a strong portion of the expected troubleshooting checks.")
        if int(score_detail.get("correctness", 0) or 0) >= 20:
            strengths.append("Your ticket handling aligned well with the expected resolution path.")
        if int(score_detail.get("sla", 0) or 0) >= 8:
            strengths.append("Your response timing stayed close to the configured SLA target.")
        if not strengths:
            strengths.append("You kept the ticket moving, but the fundamentals need more structure.")
        return strengths[:3]

    @staticmethod
    def _build_focus_areas(score_detail: dict[str, object], missed_checks: list[object]) -> list[str]:
        focus_areas: list[str] = []
        missed = [str(item).strip() for item in missed_checks if str(item).strip()]
        if missed:
            focus_areas.append(
                "Revisit the expected troubleshooting checks you skipped: "
                + ", ".join(missed[:3])
                + "."
            )
        if int(score_detail.get("correctness", 0) or 0) < 20:
            focus_areas.append("Validate the likely root cause before you move to closure.")
        if int(score_detail.get("documentation", 0) or 0) < 10:
            focus_areas.append("Document impact, troubleshooting, root cause, and resolution explicitly in the ticket.")
        if int(score_detail.get("communication", 0) or 0) < 8:
            focus_areas.append("Ask narrower follow-up questions so the user can answer directly.")
        return focus_areas[:4]

    @staticmethod
    def _build_documentation_critique(interactions: list[InteractionRecord]) -> str:
        agent_text = "\n".join(
            row.body.lower()
            for row in interactions
            if row.actor == "agent" and row.body.strip()
        )
        required_sections = ["impact", "troubleshooting", "root cause", "resolution"]
        missing = [section for section in required_sections if section not in agent_text]
        if not agent_text:
            return "No analyst notes were captured, so documentation quality could not be validated."
        if not missing:
            return "Your documentation included the core sections expected for a clean ticket record."
        return "Your notes are missing explicit coverage for: " + ", ".join(missing) + "."

    @staticmethod
    def _build_professionalism_critique(interactions: list[InteractionRecord]) -> str:
        agent_messages = [
            row.body.strip()
            for row in interactions
            if row.actor == "agent" and row.body.strip()
        ]
        if not agent_messages:
            return "No analyst messages were captured, so professionalism could not be reviewed."

        lowered = "\n".join(message.lower() for message in agent_messages)
        flagged_phrases = [
            "you're fired",
            "you are fired",
            "shut up",
            "idiot",
            "stupid",
            "that's dumb",
            "not my problem",
        ]
        found = [phrase for phrase in flagged_phrases if phrase in lowered]
        if found:
            quoted = ", ".join(f"'{phrase}'" for phrase in found[:3])
            return (
                "Your analyst messages included unprofessional language "
                f"({quoted}). Keep the tone professional and relevant to the user issue."
            )
        return "No major professionalism issues were detected in the analyst replies that were captured."

    @staticmethod
    def _build_deterministic_note(
        ticket: TicketRecord,
        score_detail: dict[str, object],
        metrics: dict[str, object],
        strengths: list[str],
        focus_areas: list[str],
        documentation_critique: str,
        professionalism_critique: str,
    ) -> str:
        total = int(score_detail.get("total", 0) or 0)
        first_response = metrics.get("first_response_minutes", "n/a")
        resolution = metrics.get("resolution_minutes", "n/a")
        note_parts = [
            f"Ticket review for '{ticket.subject}': total score {total}.",
            strengths[0],
            professionalism_critique,
            documentation_critique,
            f"First response was {first_response} minutes and resolution was {resolution} minutes.",
        ]
        if focus_areas:
            note_parts.append("Next time, focus on: " + " ".join(focus_areas[:2]))
        return " ".join(part.strip() for part in note_parts if part.strip())

    def _generate_llm_note(
        self,
        ticket: TicketRecord,
        score_detail: dict[str, object],
        metrics: dict[str, object],
        strengths: list[str],
        focus_areas: list[str],
        documentation_critique: str,
        professionalism_critique: str,
    ) -> str:
        prompt = "\n".join(
            [
                "You are a senior IT support mentor reviewing a completed help desk ticket.",
                "Use only the provided facts. Do not invent missing details.",
                "Write one concise coaching note in plain English.",
                "Keep the tone professional, direct, and useful.",
                f"Ticket subject: {ticket.subject}",
                f"Tier: {ticket.tier.value}",
                f"Priority: {ticket.priority.value}",
                f"Score breakdown: {score_detail}",
                f"Timing metrics: {metrics}",
                "Strengths:",
                *[f"- {item}" for item in strengths],
                "Focus areas:",
                *([f"- {item}" for item in focus_areas] or ["- No major focus areas recorded."]),
                f"Professionalism critique: {professionalism_critique}",
                f"Documentation critique: {documentation_critique}",
                "Return only the coaching note text.",
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
            raise RuntimeError("Ollama returned an empty coaching note")
        return text
