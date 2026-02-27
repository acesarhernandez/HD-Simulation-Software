from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from helpdesk_sim.domain.models import HintLevel


class ResponseEngine(Protocol):
    def generate_reply(self, agent_message: str, hidden_truth: dict[str, object]) -> str:
        ...


@dataclass(slots=True)
class RuleBasedResponseEngine:
    fallback_message: str = "I can provide more details if you tell me what to check next."

    def generate_reply(self, agent_message: str, hidden_truth: dict[str, object]) -> str:
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


@dataclass(slots=True)
class OllamaResponseEngine:
    base_url: str
    model: str
    timeout_seconds: float = 30.0

    def generate_reply(self, agent_message: str, hidden_truth: dict[str, object]) -> str:
        system_prompt = (
            "You are an end user replying in an IT support ticket. "
            "Do not reveal root cause unless directly proven. Keep replies short and realistic."
        )
        prompt = (
            f"Agent message: {agent_message}\n"
            f"Hidden scenario context: {hidden_truth}\n"
            "Write the end-user response only."
        )

        payload = {
            "model": self.model,
            "prompt": f"{system_prompt}\n\n{prompt}",
            "stream": False,
        }
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            text = str(data.get("response", "")).strip()
            return text or "I can provide more details if needed."


def get_hint_for_level(hidden_truth: dict[str, object], level: HintLevel) -> str:
    hint_bank = hidden_truth.get("hint_bank", {})
    if isinstance(hint_bank, dict):
        return str(hint_bank.get(level.value) or hint_bank.get(level.name) or "No hint available.")
    return "No hint available."
