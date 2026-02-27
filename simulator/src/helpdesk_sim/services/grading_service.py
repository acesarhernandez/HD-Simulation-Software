from __future__ import annotations

from datetime import datetime

from helpdesk_sim.domain.models import InteractionRecord, SessionProfile, TicketRecord, TicketScore


class GradingService:
    def grade_ticket(
        self,
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
        profile: SessionProfile,
    ) -> dict[str, object]:
        score = TicketScore()
        hidden_truth = ticket.hidden_truth

        agent_messages = [
            interaction.body.lower() for interaction in interactions if interaction.actor == "agent"
        ]
        agent_text = "\n".join(agent_messages)

        expected_checks = [
            str(check).lower() for check in hidden_truth.get("expected_agent_checks", [])
        ]
        check_hits = sum(1 for check in expected_checks if check and check in agent_text)
        if expected_checks:
            score.troubleshooting = round(25 * (check_hits / len(expected_checks)))

        correctness_keywords = [
            str(keyword).lower() for keyword in hidden_truth.get("acceptable_resolution_keywords", [])
        ]
        if correctness_keywords and any(keyword in agent_text for keyword in correctness_keywords):
            score.correctness = 30
        elif str(hidden_truth.get("root_cause", "")).lower() in agent_text:
            score.correctness = 20
        else:
            score.correctness = 8

        communication_keywords = ["please", "thanks", "let me know", "could you"]
        comm_hits = sum(1 for token in communication_keywords if token in agent_text)
        question_count = agent_text.count("?")
        score.communication = min(15, comm_hits * 3 + min(question_count, 3))

        documentation_sections = [
            "impact",
            "troubleshooting",
            "root cause",
            "resolution",
        ]
        doc_hits = sum(1 for section in documentation_sections if section in agent_text)
        score.documentation = min(15, doc_hits * 4)

        timing = self._calculate_timing(ticket, interactions)
        priority_key = ticket.priority.value
        first_response_target = profile.sla_policy.first_response_minutes.get(priority_key)
        resolution_target = profile.sla_policy.resolution_minutes.get(priority_key)

        score.sla = 10
        if first_response_target is not None and timing["first_response_minutes"] > first_response_target:
            score.sla -= 5
        if resolution_target is not None and timing["resolution_minutes"] > resolution_target:
            score.sla -= 5
        score.sla = max(score.sla, 0)

        if ticket.tier.value in {"tier2", "sysadmin"}:
            score.escalation = 5 if "escalat" in agent_text or "tier 2" in agent_text else 2
        else:
            score.escalation = 5 if "escalat" not in agent_text else 2

        score.hint_penalty = int(hidden_truth.get("hint_penalty_total", 0))

        return {
            "score": {
                "troubleshooting": score.troubleshooting,
                "correctness": score.correctness,
                "communication": score.communication,
                "documentation": score.documentation,
                "sla": score.sla,
                "escalation": score.escalation,
                "hint_penalty": score.hint_penalty,
                "total": score.total,
            },
            "metrics": timing,
            "missed_checks": [
                check
                for check in expected_checks
                if check and check not in agent_text
            ],
        }

    @staticmethod
    def _calculate_timing(
        ticket: TicketRecord,
        interactions: list[InteractionRecord],
    ) -> dict[str, float]:
        created_at = ticket.created_at
        closed_at = ticket.closed_at or datetime.now(tz=created_at.tzinfo)

        agent_interactions = [row for row in interactions if row.actor == "agent"]
        first_agent_response = agent_interactions[0].created_at if agent_interactions else closed_at

        first_response_minutes = (first_agent_response - created_at).total_seconds() / 60
        resolution_minutes = (closed_at - created_at).total_seconds() / 60

        return {
            "first_response_minutes": round(first_response_minutes, 2),
            "resolution_minutes": round(resolution_minutes, 2),
        }
