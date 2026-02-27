from __future__ import annotations

import random
from dataclasses import dataclass

from helpdesk_sim.domain.models import GeneratedTicket, SessionProfile, TicketTier
from helpdesk_sim.services.catalog_service import CatalogService


@dataclass(slots=True)
class GenerationService:
    catalog: CatalogService
    rng: random.Random = random.Random()

    def build_ticket(
        self,
        session_id: str,
        profile: SessionProfile,
        required_tags: list[str] | None = None,
        forced_tier: TicketTier | None = None,
        forced_ticket_type: str | None = None,
        forced_department: str | None = None,
        forced_persona_id: str | None = None,
        forced_scenario_id: str | None = None,
    ) -> GeneratedTicket:
        tier = forced_tier or self._pick_tier(profile)
        scenario = self.catalog.pick_scenario(
            tier=tier,
            scenario_type_weights=profile.scenario_type_weights,
            required_tags=required_tags,
            ticket_type=forced_ticket_type,
            scenario_id=forced_scenario_id,
        )
        persona = self.catalog.pick_persona(
            scenario,
            role=forced_department,
            persona_id=forced_persona_id,
        )

        subject = scenario.title
        body = scenario.customer_problem

        hidden_truth = {
            "scenario_id": scenario.id,
            "ticket_type": scenario.ticket_type,
            "root_cause": scenario.root_cause,
            "expected_agent_checks": scenario.expected_agent_checks,
            "resolution_steps": scenario.resolution_steps,
            "acceptable_resolution_keywords": scenario.acceptable_resolution_keywords,
            "knowledge_article_ids": scenario.knowledge_article_ids,
            "clue_map": scenario.clue_map,
            "hint_bank": {k.value: v for k, v in scenario.hint_bank.items()},
            "default_follow_up": scenario.default_follow_up,
            "hint_penalty_total": 0,
            "persona": {
                "id": persona.id,
                "role": persona.role,
                "full_name": persona.full_name,
                "email": persona.email,
                "technical_level": persona.technical_level,
                "tone": persona.tone,
            },
        }

        return GeneratedTicket(
            scenario_id=scenario.id,
            session_id=session_id,
            subject=subject,
            body=body,
            tier=tier,
            priority=scenario.priority,
            customer_name=persona.full_name,
            customer_email=persona.email,
            hidden_truth=hidden_truth,
        )

    def _pick_tier(self, profile: SessionProfile) -> TicketTier:
        tiers = list(profile.tier_weights.keys())
        weights = [profile.tier_weights[tier] for tier in tiers]
        return self.rng.choices(tiers, weights=weights, k=1)[0]
