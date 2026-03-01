from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TicketTier(str, Enum):
    tier1 = "tier1"
    tier2 = "tier2"
    sysadmin = "sysadmin"


class TicketPriority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"


class SessionStatus(str, Enum):
    active = "active"
    completed = "completed"


class TicketStatus(str, Enum):
    open = "open"
    closed = "closed"


class HintLevel(str, Enum):
    nudge = "nudge"
    guided_step = "guided_step"
    strong_hint = "strong_hint"


class SlaPolicy(BaseModel):
    first_response_minutes: dict[str, int] = Field(default_factory=dict)
    resolution_minutes: dict[str, int] = Field(default_factory=dict)


class HintPolicy(BaseModel):
    enabled: bool = True
    penalties: dict[HintLevel, int] = Field(
        default_factory=lambda: {
            HintLevel.nudge: 2,
            HintLevel.guided_step: 5,
            HintLevel.strong_hint: 10,
        }
    )


class IncidentInjection(BaseModel):
    name: str
    at_window: int = Field(ge=0)
    extra_tickets: int = Field(default=1, ge=0)
    scenario_tags: list[str] = Field(default_factory=list)


class SessionProfile(BaseModel):
    name: str
    description: str = ""
    duration_hours: int = Field(default=8, ge=1, le=24)
    cadence_minutes: int = Field(default=60, ge=5, le=480)
    tickets_per_window_min: int = Field(default=1, ge=0)
    tickets_per_window_max: int = Field(default=3, ge=0)
    trickle_mode: bool = True
    trickle_max_per_tick: int = Field(default=1, ge=1, le=25)
    business_hours_only: bool = False
    tier_weights: dict[TicketTier, int] = Field(
        default_factory=lambda: {
            TicketTier.tier1: 70,
            TicketTier.tier2: 20,
            TicketTier.sysadmin: 10,
        }
    )
    scenario_type_weights: dict[str, int] = Field(default_factory=dict)
    incident_injections: list[IncidentInjection] = Field(default_factory=list)
    sla_policy: SlaPolicy = Field(default_factory=SlaPolicy)
    hint_policy: HintPolicy = Field(default_factory=HintPolicy)

    @model_validator(mode="after")
    def check_ticket_range(self) -> "SessionProfile":
        if self.tickets_per_window_max < self.tickets_per_window_min:
            raise ValueError("tickets_per_window_max must be >= tickets_per_window_min")
        return self


class Persona(BaseModel):
    id: str
    role: str
    full_name: str
    email: str
    technical_level: str
    tone: str


class KnowledgeArticle(BaseModel):
    id: str
    title: str
    url: str
    summary: str = ""
    tags: list[str] = Field(default_factory=list)


class ScenarioTemplate(BaseModel):
    id: str
    title: str
    ticket_type: str
    tier: TicketTier
    priority: TicketPriority
    tags: list[str] = Field(default_factory=list)
    persona_roles: list[str] = Field(default_factory=list)
    knowledge_article_ids: list[str] = Field(default_factory=list)
    customer_problem: str
    root_cause: str
    expected_agent_checks: list[str] = Field(default_factory=list)
    resolution_steps: list[str] = Field(default_factory=list)
    acceptable_resolution_keywords: list[str] = Field(default_factory=list)
    clue_map: dict[str, str] = Field(default_factory=dict)
    hint_bank: dict[HintLevel, str] = Field(default_factory=dict)
    default_follow_up: str = "I can share more details if you can tell me exactly what you need."

    @field_validator("hint_bank", mode="before")
    @classmethod
    def parse_hint_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized: dict[HintLevel, str] = {}
        for key, hint in value.items():
            normalized[HintLevel(str(key))] = str(hint)
        return normalized


class GeneratedTicket(BaseModel):
    scenario_id: str
    session_id: str
    subject: str
    body: str
    tier: TicketTier
    priority: TicketPriority
    customer_name: str
    customer_email: str
    hidden_truth: dict[str, Any]


class TicketScore(BaseModel):
    troubleshooting: int = 0
    correctness: int = 0
    communication: int = 0
    documentation: int = 0
    sla: int = 0
    escalation: int = 0
    hint_penalty: int = 0

    @property
    def total(self) -> int:
        score = (
            self.troubleshooting
            + self.correctness
            + self.communication
            + self.documentation
            + self.sla
            + self.escalation
            - self.hint_penalty
        )
        return max(score, 0)


class SessionRecord(BaseModel):
    id: str
    profile_name: str
    status: SessionStatus
    started_at: datetime
    ends_at: datetime
    next_window_at: datetime
    window_index: int
    config: dict[str, Any]


class TicketRecord(BaseModel):
    id: str
    session_id: str
    zammad_ticket_id: int | None = None
    subject: str
    tier: TicketTier
    priority: TicketPriority
    status: TicketStatus
    scenario_id: str
    hidden_truth: dict[str, Any]
    score: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    last_seen_article_id: int = 0


class InteractionRecord(BaseModel):
    id: str
    ticket_id: str
    actor: str
    body: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportRecord(BaseModel):
    id: str
    report_type: str
    period_start: datetime
    period_end: datetime
    payload: dict[str, Any]
    created_at: datetime


class ClockInRequest(BaseModel):
    profile_name: str
    start_now: bool = True


class HintRequest(BaseModel):
    ticket_id: str
    level: HintLevel


class MentorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ManualTicketRequest(BaseModel):
    session_id: str | None = None
    count: int = Field(default=1, ge=1, le=20)
    tier: TicketTier | None = None
    ticket_type: str | None = None
    department: str | None = None
    persona_id: str | None = None
    scenario_id: str | None = None
    required_tags: list[str] = Field(default_factory=list)

    @field_validator("session_id", "ticket_type", "department", "persona_id", "scenario_id", mode="before")
    @classmethod
    def normalize_empty_strings(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class HintResponse(BaseModel):
    ticket_id: str
    level: HintLevel
    hint: str
    penalty_applied: int


class ReportSummary(BaseModel):
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    tickets_closed: int
    average_score: float
    average_first_response_minutes: float
    average_resolution_minutes: float
    sla_miss_rate: float
    top_missed_checks: list[str] = Field(default_factory=list)
