from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from helpdesk_sim.domain.models import HintLevel


class ResponseEngine(Protocol):
    def generate_reply(
        self,
        agent_message: str,
        hidden_truth: dict[str, object],
        recent_interactions: list[dict[str, object]] | None = None,
    ) -> str:
        ...

    def describe_status(self) -> dict[str, object]:
        ...


@dataclass(slots=True)
class RuleBasedResponseEngine:
    fallback_message: str = "I can provide more details if you tell me what to check next."
    generated_reply_count: int = 0

    def generate_reply(
        self,
        agent_message: str,
        hidden_truth: dict[str, object],
        recent_interactions: list[dict[str, object]] | None = None,
    ) -> str:
        self.generated_reply_count += 1
        agent_lower = agent_message.lower()
        clue_map = hidden_truth.get("clue_map", {})
        if isinstance(clue_map, dict):
            for key, response in clue_map.items():
                if self._question_matches_key(agent_lower, str(key).lower()):
                    return str(response)

        contextual = self._contextual_reply(agent_lower, hidden_truth)
        if contextual:
            return contextual

        if "screenshot" in agent_lower:
            return "I can send one in a few minutes, but right now I can only describe what I see."
        if "error" in agent_lower:
            return "The message says access denied and it started this morning."

        return str(hidden_truth.get("default_follow_up", self.fallback_message))

    @staticmethod
    def _question_matches_key(agent_lower: str, clue_key: str) -> bool:
        if clue_key in agent_lower:
            return True

        aliases = {
            "username": ["username", "user name", "which user", "who is impacted", "who is this for"],
            "error": ["error", "exact message", "what message", "what does it say"],
            "mfa": ["mfa", "2fa", "two factor", "authenticator", "verification code"],
            "scope": ["where", "what system", "which system", "sign in", "login", "log in"],
            "permission": ["permission", "access", "rights", "role"],
            "account": ["account", "profile", "user account"],
            "restart": ["restart", "reboot"],
            "sync": ["sync", "replication"],
            "version": ["version", "update"],
            "wifi": ["wifi", "internet", "network"],
            "trace": ["trace", "mail flow", "delivery"],
            "attachment": ["attachment", "pdf", "file"],
            "scope_segment": ["scope", "segment", "affected users"],
        }
        for alias in aliases.get(clue_key, []):
            if alias in agent_lower:
                return True
        return False

    @staticmethod
    def _contextual_reply(agent_lower: str, hidden_truth: dict[str, object]) -> str | None:
        ticket_type = str(hidden_truth.get("ticket_type", "")).lower()

        asks_where = any(token in agent_lower for token in ["where", "which system", "what system"])
        asks_signin = any(token in agent_lower for token in ["sign in", "login", "log in"])
        asks_detail = any(token in agent_lower for token in ["clarify", "more detail", "details", "what do you need"])

        if ticket_type == "password_reset" and (asks_where or asks_signin or asks_detail):
            return (
                "I am trying to sign in to my Windows workstation at the office. "
                "It says my password has expired."
            )

        if ticket_type == "access_request" and asks_detail:
            return "I can sign in, but I still cannot access the feature I mentioned in the ticket."

        if ticket_type == "vpn_issue" and asks_detail:
            return "I can connect, but the VPN drops every few minutes while I work."

        return None

    def describe_status(self) -> dict[str, object]:
        return {
            "configured_engine": "rule_based",
            "active_mode": "rule_based",
            "llm_enabled": False,
            "llm_optional": True,
            "fallback_enabled": False,
            "generated_reply_count": self.generated_reply_count,
        }


@dataclass(slots=True)
class OllamaResponseEngine:
    base_url: str
    model: str
    timeout_seconds: float = 30.0
    fallback_engine: ResponseEngine | None = None
    successful_llm_reply_count: int = 0
    fallback_reply_count: int = 0
    last_reply_mode: str = "not_used_yet"
    last_error: str | None = None

    def generate_reply(
        self,
        agent_message: str,
        hidden_truth: dict[str, object],
        recent_interactions: list[dict[str, object]] | None = None,
    ) -> str:
        system_prompt = self._build_system_prompt(agent_message, hidden_truth, recent_interactions)
        prompt = self._build_prompt(agent_message, hidden_truth, recent_interactions)

        payload = {
            "model": self.model,
            "prompt": f"{system_prompt}\n\n{prompt}",
            "stream": False,
        }
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                response = client.post("/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
                text = str(data.get("response", "")).strip()
                if not text:
                    raise RuntimeError("Ollama returned an empty response")
                if self._response_needs_fallback(agent_message, text):
                    raise RuntimeError("Ollama returned a vague response; using fallback")
                self.successful_llm_reply_count += 1
                self.last_reply_mode = "ollama"
                self.last_error = None
                return text
        except Exception as exc:
            self.last_error = str(exc)
            if self.fallback_engine is not None:
                self.fallback_reply_count += 1
                self.last_reply_mode = "fallback_rule_based"
                return self.fallback_engine.generate_reply(agent_message, hidden_truth)
            self.last_reply_mode = "error"
            raise

    def describe_status(self) -> dict[str, object]:
        fallback_name = None
        if self.fallback_engine is not None:
            fallback_name = self.fallback_engine.describe_status().get("configured_engine")
        return {
            "configured_engine": "ollama",
            "active_mode": self.last_reply_mode,
            "llm_enabled": True,
            "llm_optional": True,
            "fallback_enabled": self.fallback_engine is not None,
            "fallback_engine": fallback_name,
            "ollama_url": self.base_url,
            "ollama_model": self.model,
            "successful_llm_reply_count": self.successful_llm_reply_count,
            "fallback_reply_count": self.fallback_reply_count,
            "last_error": self.last_error,
        }

    @staticmethod
    def _build_system_prompt(
        agent_message: str,
        hidden_truth: dict[str, object],
        recent_interactions: list[dict[str, object]] | None,
    ) -> str:
        persona = hidden_truth.get("persona", {})
        persona_name = "the user"
        persona_role = "employee"
        technical_level = "medium"
        tone = "neutral"
        if isinstance(persona, dict):
            persona_name = str(persona.get("full_name") or persona_name)
            persona_role = str(persona.get("role") or persona_role)
            technical_level = str(persona.get("technical_level") or technical_level)
            tone = str(persona.get("tone") or tone)

        relevant_clues = OllamaResponseEngine._collect_relevant_clues(agent_message, hidden_truth)
        interaction_count = len(recent_interactions or [])

        lines = [
            "You are replying as the end user in an IT support ticket.",
            f"Persona: {persona_name}, department {persona_role}, technical level {technical_level}, tone {tone}.",
            "Write exactly one short ticket reply with no greeting and no signature.",
            "Stay realistic, cooperative, and concise.",
            "Do not reveal the hidden root cause unless the agent has already proven it.",
            "Do not say vague lines such as 'tell me exactly what you need' or 'I can try steps while you stay on the ticket' when the agent asked a specific question.",
            "If the agent asked for a concrete fact and the hidden context contains that fact, answer it directly.",
            "If the question is broad, give one or two useful details that move the ticket forward.",
            "Keep it to 1 to 3 sentences.",
        ]
        if relevant_clues:
            lines.append(f"Answer-relevant clues: {' | '.join(relevant_clues)}.")
        if interaction_count:
            lines.append(
                f"There are {interaction_count} recent ticket messages. "
                "Stay consistent with that history."
            )
        return " ".join(lines)

    @staticmethod
    def _build_prompt(
        agent_message: str,
        hidden_truth: dict[str, object],
        recent_interactions: list[dict[str, object]] | None,
    ) -> str:
        ticket_type = str(hidden_truth.get("ticket_type", "general")).strip() or "general"
        customer_problem = str(hidden_truth.get("customer_problem", "")).strip()
        default_follow_up = str(hidden_truth.get("default_follow_up", "")).strip()
        clue_map = hidden_truth.get("clue_map", {})
        clue_lines: list[str] = []
        if isinstance(clue_map, dict):
            for key, value in clue_map.items():
                clue_lines.append(f"- {key}: {value}")

        interaction_lines: list[str] = []
        for row in recent_interactions or []:
            actor = str(row.get("actor", "unknown")).strip() or "unknown"
            body = str(row.get("body", "")).strip()
            if not body:
                continue
            interaction_lines.append(f"- {actor}: {body}")
        if not interaction_lines:
            interaction_lines.append("- No prior interaction history available.")

        sections = [
            f"Ticket type: {ticket_type}",
        ]
        if customer_problem:
            sections.append(f"Original user problem: {customer_problem}")
        if default_follow_up:
            sections.append(f"Fallback style: {default_follow_up}")
        if clue_lines:
            sections.append("Known user-facing clues:\n" + "\n".join(clue_lines))
        sections.append("Recent ticket conversation:\n" + "\n".join(interaction_lines[-6:]))
        sections.append(f"Latest agent message:\n{agent_message}")
        sections.append("Reply as the end user now. Output only the reply text.")
        return "\n\n".join(sections)

    @staticmethod
    def _collect_relevant_clues(agent_message: str, hidden_truth: dict[str, object]) -> list[str]:
        clue_map = hidden_truth.get("clue_map", {})
        if not isinstance(clue_map, dict):
            return []

        lowered = agent_message.lower()
        relevant: list[str] = []
        for key, value in clue_map.items():
            clue_key = str(key).lower()
            if RuleBasedResponseEngine._question_matches_key(lowered, clue_key):
                relevant.append(f"{key}: {value}")
        return relevant[:4]

    @staticmethod
    def _response_needs_fallback(agent_message: str, text: str) -> bool:
        lowered = text.lower()
        generic_markers = [
            "tell me exactly what you need",
            "tell me what you need",
            "i can provide more details if needed",
            "i can provide more details if you need",
            "i can try steps while you stay on the ticket",
            "let me know what you need",
        ]
        if any(marker in lowered for marker in generic_markers):
            return True

        asks_direct_question = "?" in agent_message or any(
            token in agent_message.lower()
            for token in ["which", "what", "where", "who", "when", "can you tell me", "could you tell me"]
        )
        if asks_direct_question and len(lowered.split()) <= 4:
            return True
        return False


def get_hint_for_level(hidden_truth: dict[str, object], level: HintLevel) -> str:
    hint_bank = hidden_truth.get("hint_bank", {})
    if isinstance(hint_bank, dict):
        return str(hint_bank.get(level.value) or hint_bank.get(level.name) or "No hint available.")
    return "No hint available."
