from __future__ import annotations

import random
from pathlib import Path

import yaml

from helpdesk_sim.domain.models import (
    KnowledgeArticle,
    Persona,
    ScenarioTemplate,
    SessionProfile,
    TicketTier,
)


class CatalogService:
    def __init__(self, templates_dir: Path, rng: random.Random | None = None) -> None:
        self.templates_dir = templates_dir
        self._rng = rng or random.Random()
        self._profiles: dict[str, SessionProfile] = {}
        self._personas: list[Persona] = []
        self._scenarios: list[ScenarioTemplate] = []
        self._knowledge_articles: dict[str, KnowledgeArticle] = {}

    def load(self) -> None:
        profiles_data = self._load_yaml(self.templates_dir / "profiles.yaml")
        personas_data = self._load_yaml(self.templates_dir / "personas.yaml")
        scenarios_data = self._load_yaml(self.templates_dir / "scenarios.yaml")
        knowledge_data = self._load_yaml(self.templates_dir / "knowledge_articles.yaml")

        self._profiles = {
            row["name"]: SessionProfile.model_validate(row)
            for row in profiles_data.get("profiles", [])
        }
        self._personas = [
            Persona.model_validate(row) for row in personas_data.get("personas", [])
        ]
        self._scenarios = [
            ScenarioTemplate.model_validate(row) for row in scenarios_data.get("scenarios", [])
        ]
        self._knowledge_articles = {
            row["id"]: KnowledgeArticle.model_validate(row)
            for row in knowledge_data.get("articles", [])
        }

    def list_profiles(self) -> list[str]:
        return sorted(self._profiles.keys())

    def list_profile_definitions(self) -> list[SessionProfile]:
        return [self._profiles[name] for name in self.list_profiles()]

    def get_profile(self, name: str) -> SessionProfile:
        profile = self._profiles.get(name)
        if profile is None:
            available = ", ".join(self.list_profiles())
            raise ValueError(f"unknown profile '{name}'. Available: {available}")
        return profile

    def pick_scenario(
        self,
        tier: TicketTier,
        scenario_type_weights: dict[str, int] | None = None,
        required_tags: list[str] | None = None,
        ticket_type: str | None = None,
        scenario_id: str | None = None,
    ) -> ScenarioTemplate:
        if scenario_id:
            scenario = next((row for row in self._scenarios if row.id == scenario_id), None)
            if scenario is None:
                raise ValueError(f"scenario '{scenario_id}' was not found")
            if scenario.tier != tier:
                raise ValueError(
                    f"scenario '{scenario_id}' is tier '{scenario.tier.value}', not '{tier.value}'"
                )
            return scenario

        required_tags = required_tags or []
        candidates = [
            scenario
            for scenario in self._scenarios
            if scenario.tier == tier and all(tag in scenario.tags for tag in required_tags)
        ]
        if ticket_type:
            candidates = [scenario for scenario in candidates if scenario.ticket_type == ticket_type]
        if not candidates:
            candidates = [scenario for scenario in self._scenarios if scenario.tier == tier]
            if ticket_type:
                candidates = [
                    scenario for scenario in candidates if scenario.ticket_type == ticket_type
                ]
        if not candidates:
            raise ValueError(f"no scenarios configured for tier '{tier.value}'")

        weights: list[float] = []
        for scenario in candidates:
            base = 1.0
            if scenario_type_weights:
                base = float(scenario_type_weights.get(scenario.ticket_type, 1))
            weights.append(base)

        return self._rng.choices(candidates, weights=weights, k=1)[0]

    def pick_persona(
        self,
        scenario: ScenarioTemplate,
        role: str | None = None,
        persona_id: str | None = None,
    ) -> Persona:
        candidates = [
            persona
            for persona in self._personas
            if not scenario.persona_roles or persona.role in scenario.persona_roles
        ]
        if role:
            candidates = [persona for persona in candidates if persona.role == role]
        if persona_id:
            candidates = [persona for persona in candidates if persona.id == persona_id]
        if not candidates:
            raise ValueError(f"no persona matches scenario {scenario.id}")
        return self._rng.choice(candidates)

    def get_knowledge_articles(self, article_ids: list[str]) -> list[KnowledgeArticle]:
        articles: list[KnowledgeArticle] = []
        for article_id in article_ids:
            article = self._knowledge_articles.get(article_id)
            if article is not None:
                articles.append(article)
        return articles

    def list_knowledge_articles(self) -> list[KnowledgeArticle]:
        return sorted(self._knowledge_articles.values(), key=lambda article: article.id)

    def list_personas(self) -> list[Persona]:
        return sorted(self._personas, key=lambda persona: persona.id)

    def list_scenarios(self) -> list[ScenarioTemplate]:
        return sorted(self._scenarios, key=lambda scenario: scenario.id)

    def list_ticket_types(self) -> list[str]:
        return sorted({scenario.ticket_type for scenario in self._scenarios})

    def list_departments(self) -> list[str]:
        return sorted({persona.role for persona in self._personas})

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"template file not found: {path}")
        with path.open("r", encoding="utf-8") as stream:
            return yaml.safe_load(stream) or {}
