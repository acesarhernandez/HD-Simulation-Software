from __future__ import annotations

from helpdesk_sim.domain.models import HintLevel, HintResponse, SessionProfile
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.response_engine import get_hint_for_level


class HintService:
    def __init__(self, repository: SimulatorRepository) -> None:
        self.repository = repository

    def request_hint(self, ticket_id: str, level: HintLevel) -> HintResponse:
        ticket = self.repository.get_ticket(ticket_id)
        if ticket is None:
            raise ValueError(f"ticket '{ticket_id}' does not exist")

        session = self.repository.get_session(ticket.session_id)
        if session is None:
            raise ValueError(f"session '{ticket.session_id}' does not exist")

        profile = SessionProfile.model_validate(session.config)
        if not profile.hint_policy.enabled:
            raise ValueError("hints are disabled for this session profile")

        penalty = int(profile.hint_policy.penalties.get(level, 0))
        hidden_truth = dict(ticket.hidden_truth)
        hidden_truth["hint_penalty_total"] = int(hidden_truth.get("hint_penalty_total", 0)) + penalty
        self.repository.update_ticket_hidden_truth(ticket_id=ticket_id, hidden_truth=hidden_truth)

        hint_text = get_hint_for_level(hidden_truth, level)
        self.repository.add_interaction(
            ticket_id=ticket_id,
            actor="system",
            body=f"Hint requested: {level.value}",
            metadata={"event": "hint", "level": level.value, "penalty": penalty},
        )

        return HintResponse(
            ticket_id=ticket_id,
            level=level,
            hint=hint_text,
            penalty_applied=penalty,
        )
