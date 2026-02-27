from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Literal

from helpdesk_sim.domain.models import ReportSummary
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.utils import utc_now


class ReportService:
    def __init__(self, repository: SimulatorRepository) -> None:
        self.repository = repository

    def generate(self, report_type: Literal["daily", "weekly"]) -> dict[str, object]:
        now = utc_now()
        if report_type == "daily":
            period_start = now - timedelta(days=1)
        elif report_type == "weekly":
            period_start = now - timedelta(days=7)
        else:
            raise ValueError("report_type must be 'daily' or 'weekly'")

        closed_tickets = self.repository.list_closed_tickets_between(period_start, now)

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

        previous = self.repository.latest_report(report_type)
        compare = None
        if previous is not None:
            previous_avg = float(previous.payload.get("average_score", 0.0))
            compare = {
                "previous_average_score": previous_avg,
                "score_delta": round(summary.average_score - previous_avg, 2),
            }

        payload = summary.model_dump(mode="json")
        if compare is not None:
            payload["comparison"] = compare

        self.repository.save_report(
            report_type=report_type,
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
