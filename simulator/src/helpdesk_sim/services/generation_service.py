from __future__ import annotations

import random
from dataclasses import dataclass

import httpx

from helpdesk_sim.domain.models import GeneratedTicket, SessionProfile, TicketTier
from helpdesk_sim.services.catalog_service import CatalogService


@dataclass(slots=True)
class GenerationService:
    catalog: CatalogService
    rng: random.Random = random.Random()
    llm_enabled: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    rewrite_opening_tickets: bool = True
    timeout_seconds: float = 20.0

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
        if self.llm_enabled and self.rewrite_opening_tickets:
            body = self._rewrite_opening_body(
                subject=subject,
                body=body,
                scenario=scenario,
                persona=persona,
            )

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
            "template_subject": scenario.title,
            "template_body": scenario.customer_problem,
            "opening_body_source": "llm_rewrite" if body != scenario.customer_problem else "template",
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

    def _rewrite_opening_body(
        self,
        subject,
        body: str,
        scenario,
        persona,
    ) -> str:
        variation_style = self.rng.choice(
            [
                "Lead with the user impact first.",
                "Lead with the blocked task first.",
                "Lead with the device or work context first.",
                "Keep it brief and direct.",
            ]
        )
        prompt = "\n".join(
            [
                "You are rewriting the opening message of an IT help desk ticket.",
                "You are not changing the technical issue. You are only rewriting the wording.",
                "Do not invent a new root cause, new system, or new scope.",
                "Keep it realistic, concise, and natural.",
                "Write 1 to 3 sentences. No greeting. No signature.",
                variation_style,
                f"Ticket subject: {subject}",
                f"Ticket type: {scenario.ticket_type}",
                f"Base opening message: {body}",
                f"Persona department: {persona.role}",
                f"Persona technical level: {persona.technical_level}",
                f"Persona tone: {persona.tone}",
                f"Known safe user-facing clues: {scenario.clue_map}",
                "Return only the rewritten opening message.",
            ]
        )
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
        }
        try:
            with httpx.Client(base_url=self.ollama_url, timeout=self.timeout_seconds) as client:
                response = client.post("/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
            text = str(data.get("response", "")).strip()
            if not text:
                raise RuntimeError("Ollama returned an empty opening rewrite")
            return text
        except Exception:
            return body
