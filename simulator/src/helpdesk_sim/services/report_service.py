from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Literal

from helpdesk_sim.domain.models import ScoreMode
from helpdesk_sim.domain.models import ReportSummary
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.utils import utc_now


class ReportService:
    def __init__(self, repository: SimulatorRepository) -> None:
        self.repository = repository

    def generate(
        self,
        report_type: Literal["daily", "weekly"],
        score_mode: str | None = None,
    ) -> dict[str, object]:
        now = utc_now()
        if report_type == "daily":
            period_start = now - timedelta(days=1)
        elif report_type == "weekly":
            period_start = now - timedelta(days=7)
        else:
            raise ValueError("report_type must be 'daily' or 'weekly'")

        closed_tickets = self.repository.list_closed_tickets_between(period_start, now)
        if score_mode:
            closed_tickets = [
                ticket
                for ticket in closed_tickets
                if self._ticket_score_mode(ticket) == score_mode
            ]

        total_scores: list[float] = []
        first_response_values: list[float] = []
        resolution_values: list[float] = []
        sla_miss_count = 0
        missed_checks_counter: Counter[str] = Counter()

        for ticket in closed_tickets:
            score_payload = ticket.score or {}
            score = score_payload.get("score", {})
            metrics = score_payload.get("metrics", {})
            missed_checks = score_payload.get("missed_checks", [])

            if isinstance(score.get("total"), (int, float)):
                total_scores.append(float(score["total"]))
            if isinstance(metrics.get("first_response_minutes"), (int, float)):
                first_response_values.append(float(metrics["first_response_minutes"]))
            if isinstance(metrics.get("resolution_minutes"), (int, float)):
                resolution_values.append(float(metrics["resolution_minutes"]))
            if isinstance(score.get("sla"), (int, float)) and score["sla"] < 10:
                sla_miss_count += 1

            for check in missed_checks:
                missed_checks_counter[str(check)] += 1

        summary = ReportSummary(
            generated_at=now,
            period_start=period_start,
            period_end=now,
            tickets_closed=len(closed_tickets),
            average_score=self._average(total_scores),
            average_first_response_minutes=self._average(first_response_values),
            average_resolution_minutes=self._average(resolution_values),
            sla_miss_rate=(sla_miss_count / len(closed_tickets) if closed_tickets else 0.0),
            top_missed_checks=[item[0] for item in missed_checks_counter.most_common(5)],
        )

        report_key = self._report_key(report_type=report_type, score_mode=score_mode)
        previous = self.repository.latest_report(report_key)
        compare = None
        if previous is not None:
            previous_avg = float(previous.payload.get("average_score", 0.0))
            compare = {
                "previous_average_score": previous_avg,
                "score_delta": round(summary.average_score - previous_avg, 2),
            }

        payload = summary.model_dump(mode="json")
        payload["score_mode"] = score_mode or "all"
        if compare is not None:
            payload["comparison"] = compare

        self.repository.save_report(
            report_type=report_key,
            period_start=period_start,
            period_end=now,
            payload=payload,
        )

        return payload

    @staticmethod
    def _average(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)

    @staticmethod
    def _report_key(report_type: str, score_mode: str | None) -> str:
        if score_mode == ScoreMode.guided_training.value:
            return f"{report_type}_god"
        if score_mode == ScoreMode.practice.value:
            return report_type
        return report_type

    @staticmethod
    def _ticket_score_mode(ticket) -> str:
        score_payload = ticket.score if isinstance(ticket.score, dict) else {}
        meta = score_payload.get("meta", {}) if isinstance(score_payload, dict) else {}
        mode = str(meta.get("score_mode", "")).strip().lower()
        if mode in {ScoreMode.practice.value, ScoreMode.guided_training.value}:
            return mode

        hidden = ticket.hidden_truth if isinstance(ticket.hidden_truth, dict) else {}
        god_mode = hidden.get("god_mode", {}) if isinstance(hidden, dict) else {}
        if isinstance(god_mode, dict) and bool(god_mode.get("enabled")):
            return ScoreMode.guided_training.value
        return ScoreMode.practice.value
