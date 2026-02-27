from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from helpdesk_sim.domain.models import (
    InteractionRecord,
    ReportRecord,
    SessionRecord,
    SessionStatus,
    TicketRecord,
    TicketStatus,
)
from helpdesk_sim.utils import from_iso, to_iso, utc_now


class SimulatorRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    profile_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    next_window_at TEXT NOT NULL,
                    window_index INTEGER NOT NULL DEFAULT 0,
                    config_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    zammad_ticket_id INTEGER,
                    subject TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    hidden_truth_json TEXT NOT NULL,
                    score_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    last_seen_article_id INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT,
                    FOREIGN KEY(ticket_id) REFERENCES tickets(id)
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    report_type TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
                CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
                CREATE INDEX IF NOT EXISTS idx_tickets_session ON tickets(session_id);
                CREATE INDEX IF NOT EXISTS idx_reports_type_created ON reports(report_type, created_at);
                """
            )

    def create_session(
        self,
        profile_name: str,
        started_at: datetime,
        ends_at: datetime,
        next_window_at: datetime,
        config: dict[str, Any],
    ) -> SessionRecord:
        session_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, profile_name, status, started_at, ends_at, next_window_at, window_index, config_json)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    session_id,
                    profile_name,
                    SessionStatus.active.value,
                    to_iso(started_at),
                    to_iso(ends_at),
                    to_iso(next_window_at),
                    json.dumps(config),
                ),
            )
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("failed to create session")
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def list_active_sessions(self) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY started_at ASC",
                (SessionStatus.active.value,),
            ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def advance_session_window(self, session_id: str, next_window_at: datetime, window_index: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET next_window_at = ?, window_index = ? WHERE id = ?",
                (to_iso(next_window_at), window_index, session_id),
            )

    def update_session_config(self, session_id: str, config: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET config_json = ? WHERE id = ?",
                (json.dumps(config), session_id),
            )

    def complete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET status = ? WHERE id = ?",
                (SessionStatus.completed.value, session_id),
            )

    def create_ticket(
        self,
        session_id: str,
        subject: str,
        tier: str,
        priority: str,
        scenario_id: str,
        hidden_truth: dict[str, Any],
        zammad_ticket_id: int | None,
    ) -> TicketRecord:
        ticket_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tickets (
                    id, session_id, zammad_ticket_id, subject, tier, priority, status,
                    scenario_id, hidden_truth_json, created_at, updated_at, score_json, last_seen_article_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
                """,
                (
                    ticket_id,
                    session_id,
                    zammad_ticket_id,
                    subject,
                    tier,
                    priority,
                    TicketStatus.open.value,
                    scenario_id,
                    json.dumps(hidden_truth),
                    to_iso(now),
                    to_iso(now),
                ),
            )
        record = self.get_ticket(ticket_id)
        if record is None:
            raise RuntimeError("failed to create ticket")
        return record

    def get_ticket(self, ticket_id: str) -> TicketRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return self._row_to_ticket(row) if row else None

    def list_open_tickets(self) -> list[TicketRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY created_at ASC",
                (TicketStatus.open.value,),
            ).fetchall()
        return [self._row_to_ticket(row) for row in rows]

    def list_tickets_for_session(self, session_id: str) -> list[TicketRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [self._row_to_ticket(row) for row in rows]

    def update_ticket_last_seen_article_id(self, ticket_id: str, article_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tickets SET last_seen_article_id = ?, updated_at = ? WHERE id = ?",
                (article_id, to_iso(utc_now()), ticket_id),
            )

    def update_ticket_hidden_truth(self, ticket_id: str, hidden_truth: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tickets SET hidden_truth_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(hidden_truth), to_iso(utc_now()), ticket_id),
            )

    def close_ticket(self, ticket_id: str, score: dict[str, Any]) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = ?, score_json = ?, updated_at = ?, closed_at = ?
                WHERE id = ?
                """,
                (
                    TicketStatus.closed.value,
                    json.dumps(score),
                    to_iso(now),
                    to_iso(now),
                    ticket_id,
                ),
            )

    def close_open_tickets_for_session(self, session_id: str, score: dict[str, Any]) -> int:
        now = utc_now()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM tickets WHERE session_id = ? AND status = ?",
                (session_id, TicketStatus.open.value),
            ).fetchall()
            ticket_ids = [str(row["id"]) for row in rows]
            if not ticket_ids:
                return 0

            conn.executemany(
                """
                UPDATE tickets
                SET status = ?, score_json = ?, updated_at = ?, closed_at = ?
                WHERE id = ?
                """,
                [
                    (
                        TicketStatus.closed.value,
                        json.dumps(score),
                        to_iso(now),
                        to_iso(now),
                        ticket_id,
                    )
                    for ticket_id in ticket_ids
                ],
            )
        return len(ticket_ids)

    def delete_ticket(self, ticket_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM interactions WHERE ticket_id = ?", (ticket_id,))
            cursor = conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        return cursor.rowcount > 0

    def delete_tickets_for_session(self, session_id: str) -> int:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM interactions
                WHERE ticket_id IN (
                    SELECT id FROM tickets WHERE session_id = ?
                )
                """,
                (session_id,),
            )
            cursor = conn.execute("DELETE FROM tickets WHERE session_id = ?", (session_id,))
        return int(cursor.rowcount or 0)

    def add_interaction(
        self,
        ticket_id: str,
        actor: str,
        body: str,
        metadata: dict[str, Any] | None = None,
    ) -> InteractionRecord:
        interaction_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO interactions (id, ticket_id, actor, body, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction_id,
                    ticket_id,
                    actor,
                    body,
                    to_iso(now),
                    json.dumps(metadata or {}),
                ),
            )
            conn.execute(
                "UPDATE tickets SET updated_at = ? WHERE id = ?",
                (to_iso(now), ticket_id),
            )
        return InteractionRecord(
            id=interaction_id,
            ticket_id=ticket_id,
            actor=actor,
            body=body,
            created_at=now,
            metadata=metadata or {},
        )

    def list_interactions(self, ticket_id: str) -> list[InteractionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM interactions WHERE ticket_id = ? ORDER BY created_at ASC",
                (ticket_id,),
            ).fetchall()
        return [self._row_to_interaction(row) for row in rows]

    def list_closed_tickets_between(self, start: datetime, end: datetime) -> list[TicketRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tickets
                WHERE status = ? AND closed_at IS NOT NULL AND closed_at >= ? AND closed_at < ?
                ORDER BY closed_at ASC
                """,
                (TicketStatus.closed.value, to_iso(start), to_iso(end)),
            ).fetchall()
        return [self._row_to_ticket(row) for row in rows]

    def save_report(
        self,
        report_type: str,
        period_start: datetime,
        period_end: datetime,
        payload: dict[str, Any],
    ) -> ReportRecord:
        report_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reports (id, report_type, period_start, period_end, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    report_type,
                    to_iso(period_start),
                    to_iso(period_end),
                    json.dumps(payload),
                    to_iso(now),
                ),
            )
        return ReportRecord(
            id=report_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            payload=payload,
            created_at=now,
        )

    def latest_report(self, report_type: str) -> ReportRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reports WHERE report_type = ? ORDER BY created_at DESC LIMIT 1",
                (report_type,),
            ).fetchone()
        return self._row_to_report(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            profile_name=row["profile_name"],
            status=SessionStatus(row["status"]),
            started_at=from_iso(row["started_at"]),
            ends_at=from_iso(row["ends_at"]),
            next_window_at=from_iso(row["next_window_at"]),
            window_index=row["window_index"],
            config=json.loads(row["config_json"]),
        )

    @staticmethod
    def _row_to_ticket(row: sqlite3.Row) -> TicketRecord:
        score_json = json.loads(row["score_json"]) if row["score_json"] else None
        return TicketRecord(
            id=row["id"],
            session_id=row["session_id"],
            zammad_ticket_id=row["zammad_ticket_id"],
            subject=row["subject"],
            tier=row["tier"],
            priority=row["priority"],
            status=row["status"],
            scenario_id=row["scenario_id"],
            hidden_truth=json.loads(row["hidden_truth_json"]),
            score=score_json,
            created_at=from_iso(row["created_at"]),
            updated_at=from_iso(row["updated_at"]),
            closed_at=from_iso(row["closed_at"]) if row["closed_at"] else None,
            last_seen_article_id=row["last_seen_article_id"],
        )

    @staticmethod
    def _row_to_interaction(row: sqlite3.Row) -> InteractionRecord:
        return InteractionRecord(
            id=row["id"],
            ticket_id=row["ticket_id"],
            actor=row["actor"],
            body=row["body"],
            created_at=from_iso(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _row_to_report(row: sqlite3.Row) -> ReportRecord:
        return ReportRecord(
            id=row["id"],
            report_type=row["report_type"],
            period_start=from_iso(row["period_start"]),
            period_end=from_iso(row["period_end"]),
            payload=json.loads(row["payload_json"]),
            created_at=from_iso(row["created_at"]),
        )
