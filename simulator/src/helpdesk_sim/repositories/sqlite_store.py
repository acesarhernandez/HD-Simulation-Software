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
    KnowledgeArticleCacheEntry,
    KnowledgeProposedAction,
    KnowledgeReviewEvent,
    KnowledgeReviewItem,
    KnowledgeReviewRevision,
    KnowledgeReviewStatus,
    KnowledgeArticleType,
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

                CREATE TABLE IF NOT EXISTS kb_article_cache (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    external_article_id TEXT NOT NULL,
                    external_kb_id TEXT NOT NULL,
                    external_category_id TEXT NOT NULL,
                    locale_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body_markdown TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    last_synced_at TEXT NOT NULL,
                    version_token TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS kb_review_items (
                    id TEXT PRIMARY KEY,
                    source_ticket_id TEXT NOT NULL,
                    source_zammad_ticket_id INTEGER,
                    contributing_ticket_ids_json TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    proposed_action TEXT NOT NULL,
                    target_external_article_id TEXT,
                    article_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    body_markdown TEXT NOT NULL,
                    diff_summary_json TEXT NOT NULL,
                    matching_rationale TEXT NOT NULL,
                    llm_confidence REAL NOT NULL DEFAULT 0,
                    kb_worthiness_score INTEGER NOT NULL DEFAULT 0,
                    kb_worthiness_reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    review_notes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT,
                    published_at TEXT,
                    published_external_article_id TEXT,
                    publish_result_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS kb_review_revisions (
                    id TEXT PRIMARY KEY,
                    review_item_id TEXT NOT NULL,
                    revision_number INTEGER NOT NULL,
                    instruction_text TEXT NOT NULL,
                    body_markdown TEXT NOT NULL,
                    diff_summary_json TEXT NOT NULL,
                    llm_used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(review_item_id) REFERENCES kb_review_items(id)
                );

                CREATE TABLE IF NOT EXISTS kb_review_events (
                    id TEXT PRIMARY KEY,
                    review_item_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(review_item_id) REFERENCES kb_review_items(id)
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
                CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
                CREATE INDEX IF NOT EXISTS idx_tickets_session ON tickets(session_id);
                CREATE INDEX IF NOT EXISTS idx_reports_type_created ON reports(report_type, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_cache_provider_external ON kb_article_cache(provider, external_article_id);
                CREATE INDEX IF NOT EXISTS idx_kb_review_status ON kb_review_items(status);
                CREATE INDEX IF NOT EXISTS idx_kb_review_source_ticket ON kb_review_items(source_ticket_id);
                CREATE INDEX IF NOT EXISTS idx_kb_revisions_item ON kb_review_revisions(review_item_id, revision_number);
                CREATE INDEX IF NOT EXISTS idx_kb_events_item ON kb_review_events(review_item_id, created_at);
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

    def replace_kb_article_cache(
        self,
        provider: str,
        entries: list[KnowledgeArticleCacheEntry],
    ) -> int:
        with self._connect() as conn:
            conn.execute("DELETE FROM kb_article_cache WHERE provider = ?", (provider,))
            for entry in entries:
                conn.execute(
                    """
                    INSERT INTO kb_article_cache (
                        id, provider, external_article_id, external_kb_id, external_category_id,
                        locale_id, title, summary, body_markdown, tags_json, status,
                        fingerprint, last_synced_at, version_token
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.provider,
                        entry.external_article_id,
                        entry.external_kb_id,
                        entry.external_category_id,
                        entry.locale_id,
                        entry.title,
                        entry.summary,
                        entry.body_markdown,
                        json.dumps(entry.tags),
                        entry.status,
                        entry.fingerprint,
                        to_iso(entry.last_synced_at),
                        entry.version_token,
                    ),
                )
        return len(entries)

    def list_kb_article_cache(self, provider: str | None = None) -> list[KnowledgeArticleCacheEntry]:
        with self._connect() as conn:
            if provider:
                rows = conn.execute(
                    "SELECT * FROM kb_article_cache WHERE provider = ? ORDER BY title ASC",
                    (provider,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM kb_article_cache ORDER BY title ASC").fetchall()
        return [self._row_to_kb_article_cache(row) for row in rows]

    def get_kb_article_cache_by_external(
        self,
        provider: str,
        external_article_id: str,
    ) -> KnowledgeArticleCacheEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM kb_article_cache WHERE provider = ? AND external_article_id = ?",
                (provider, external_article_id),
            ).fetchone()
        return self._row_to_kb_article_cache(row) if row else None

    def create_kb_review_item(
        self,
        *,
        source_ticket_id: str,
        source_zammad_ticket_id: int | None,
        contributing_ticket_ids: list[str],
        provider: str,
        proposed_action: KnowledgeProposedAction,
        target_external_article_id: str | None,
        article_type: KnowledgeArticleType,
        title: str,
        summary: str,
        tags: list[str],
        body_markdown: str,
        diff_summary: dict[str, Any],
        matching_rationale: str,
        llm_confidence: float,
        kb_worthiness_score: int,
        kb_worthiness_reason: str,
        status: KnowledgeReviewStatus,
    ) -> KnowledgeReviewItem:
        item_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kb_review_items (
                    id, source_ticket_id, source_zammad_ticket_id, contributing_ticket_ids_json,
                    provider, proposed_action, target_external_article_id, article_type, title,
                    summary, tags_json, body_markdown, diff_summary_json, matching_rationale,
                    llm_confidence, kb_worthiness_score, kb_worthiness_reason, status,
                    review_notes, created_at, updated_at, approved_at, published_at,
                    published_external_article_id, publish_result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    item_id,
                    source_ticket_id,
                    source_zammad_ticket_id,
                    json.dumps(contributing_ticket_ids),
                    provider,
                    proposed_action.value,
                    target_external_article_id,
                    article_type.value,
                    title,
                    summary,
                    json.dumps(tags),
                    body_markdown,
                    json.dumps(diff_summary),
                    matching_rationale,
                    llm_confidence,
                    kb_worthiness_score,
                    kb_worthiness_reason,
                    status.value,
                    "",
                    to_iso(now),
                    to_iso(now),
                    json.dumps({}),
                ),
            )
        item = self.get_kb_review_item(item_id)
        if item is None:
            raise RuntimeError("failed to create KB review item")
        return item

    def list_kb_review_items(
        self,
        *,
        status: KnowledgeReviewStatus | None = None,
        provider: str | None = None,
        source_ticket_id: str | None = None,
    ) -> list[KnowledgeReviewItem]:
        query = "SELECT * FROM kb_review_items WHERE 1=1"
        params: list[Any] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if source_ticket_id:
            query += " AND source_ticket_id = ?"
            params.append(source_ticket_id)
        query += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_kb_review_item(row) for row in rows]

    def get_kb_review_item(self, review_item_id: str) -> KnowledgeReviewItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM kb_review_items WHERE id = ?",
                (review_item_id,),
            ).fetchone()
        return self._row_to_kb_review_item(row) if row else None

    def update_kb_review_item(
        self,
        review_item_id: str,
        *,
        body_markdown: str | None = None,
        diff_summary: dict[str, Any] | None = None,
        review_notes: str | None = None,
        status: KnowledgeReviewStatus | None = None,
        approved_at: datetime | None = None,
        published_at: datetime | None = None,
        published_external_article_id: str | None = None,
        publish_result: dict[str, Any] | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        params: list[Any] = [to_iso(utc_now())]

        if body_markdown is not None:
            fields.append("body_markdown = ?")
            params.append(body_markdown)
        if diff_summary is not None:
            fields.append("diff_summary_json = ?")
            params.append(json.dumps(diff_summary))
        if review_notes is not None:
            fields.append("review_notes = ?")
            params.append(review_notes)
        if status is not None:
            fields.append("status = ?")
            params.append(status.value)
        if approved_at is not None:
            fields.append("approved_at = ?")
            params.append(to_iso(approved_at))
        if published_at is not None:
            fields.append("published_at = ?")
            params.append(to_iso(published_at))
        if published_external_article_id is not None:
            fields.append("published_external_article_id = ?")
            params.append(published_external_article_id)
        if publish_result is not None:
            fields.append("publish_result_json = ?")
            params.append(json.dumps(publish_result))

        params.append(review_item_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE kb_review_items SET {', '.join(fields)} WHERE id = ?",
                tuple(params),
            )

    def add_kb_review_revision(
        self,
        review_item_id: str,
        *,
        instruction_text: str,
        body_markdown: str,
        diff_summary: dict[str, Any],
        llm_used: bool,
    ) -> KnowledgeReviewRevision:
        existing = self.list_kb_review_revisions(review_item_id)
        revision_number = len(existing) + 1
        revision_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kb_review_revisions (
                    id, review_item_id, revision_number, instruction_text, body_markdown,
                    diff_summary_json, llm_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    review_item_id,
                    revision_number,
                    instruction_text,
                    body_markdown,
                    json.dumps(diff_summary),
                    1 if llm_used else 0,
                    to_iso(now),
                ),
            )
        revision = self.get_kb_review_revision(revision_id)
        if revision is None:
            raise RuntimeError("failed to create KB review revision")
        return revision

    def get_kb_review_revision(self, revision_id: str) -> KnowledgeReviewRevision | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM kb_review_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        return self._row_to_kb_review_revision(row) if row else None

    def list_kb_review_revisions(self, review_item_id: str) -> list[KnowledgeReviewRevision]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM kb_review_revisions WHERE review_item_id = ? ORDER BY revision_number ASC",
                (review_item_id,),
            ).fetchall()
        return [self._row_to_kb_review_revision(row) for row in rows]

    def add_kb_review_event(
        self,
        review_item_id: str,
        *,
        event_type: str,
        actor: str,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeReviewEvent:
        event_id = str(uuid.uuid4())
        now = utc_now()
        payload = metadata or {}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kb_review_events (
                    id, review_item_id, event_type, actor, notes, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    review_item_id,
                    event_type,
                    actor,
                    notes,
                    json.dumps(payload),
                    to_iso(now),
                ),
            )
        event = self.get_kb_review_event(event_id)
        if event is None:
            raise RuntimeError("failed to create KB review event")
        return event

    def get_kb_review_event(self, event_id: str) -> KnowledgeReviewEvent | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM kb_review_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return self._row_to_kb_review_event(row) if row else None

    def list_kb_review_events(self, review_item_id: str) -> list[KnowledgeReviewEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM kb_review_events WHERE review_item_id = ? ORDER BY created_at ASC",
                (review_item_id,),
            ).fetchall()
        return [self._row_to_kb_review_event(row) for row in rows]

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

    @staticmethod
    def _row_to_kb_article_cache(row: sqlite3.Row) -> KnowledgeArticleCacheEntry:
        return KnowledgeArticleCacheEntry(
            id=row["id"],
            provider=row["provider"],
            external_article_id=row["external_article_id"],
            external_kb_id=row["external_kb_id"],
            external_category_id=row["external_category_id"],
            locale_id=row["locale_id"],
            title=row["title"],
            summary=row["summary"],
            body_markdown=row["body_markdown"],
            tags=json.loads(row["tags_json"] or "[]"),
            status=row["status"],
            fingerprint=row["fingerprint"],
            last_synced_at=from_iso(row["last_synced_at"]),
            version_token=row["version_token"],
        )

    @staticmethod
    def _row_to_kb_review_item(row: sqlite3.Row) -> KnowledgeReviewItem:
        return KnowledgeReviewItem(
            id=row["id"],
            source_ticket_id=row["source_ticket_id"],
            source_zammad_ticket_id=row["source_zammad_ticket_id"],
            contributing_ticket_ids=json.loads(row["contributing_ticket_ids_json"] or "[]"),
            provider=row["provider"],
            proposed_action=KnowledgeProposedAction(row["proposed_action"]),
            target_external_article_id=row["target_external_article_id"],
            article_type=KnowledgeArticleType(row["article_type"]),
            title=row["title"],
            summary=row["summary"],
            tags=json.loads(row["tags_json"] or "[]"),
            body_markdown=row["body_markdown"],
            diff_summary=json.loads(row["diff_summary_json"] or "{}"),
            matching_rationale=row["matching_rationale"],
            llm_confidence=float(row["llm_confidence"] or 0.0),
            kb_worthiness_score=int(row["kb_worthiness_score"] or 0),
            kb_worthiness_reason=row["kb_worthiness_reason"],
            status=KnowledgeReviewStatus(row["status"]),
            review_notes=row["review_notes"],
            created_at=from_iso(row["created_at"]),
            updated_at=from_iso(row["updated_at"]),
            approved_at=from_iso(row["approved_at"]) if row["approved_at"] else None,
            published_at=from_iso(row["published_at"]) if row["published_at"] else None,
            published_external_article_id=row["published_external_article_id"],
            publish_result=json.loads(row["publish_result_json"] or "{}"),
        )

    @staticmethod
    def _row_to_kb_review_revision(row: sqlite3.Row) -> KnowledgeReviewRevision:
        return KnowledgeReviewRevision(
            id=row["id"],
            review_item_id=row["review_item_id"],
            revision_number=int(row["revision_number"]),
            instruction_text=row["instruction_text"],
            body_markdown=row["body_markdown"],
            diff_summary=json.loads(row["diff_summary_json"] or "{}"),
            llm_used=bool(row["llm_used"]),
            created_at=from_iso(row["created_at"]),
        )

    @staticmethod
    def _row_to_kb_review_event(row: sqlite3.Row) -> KnowledgeReviewEvent:
        return KnowledgeReviewEvent(
            id=row["id"],
            review_item_id=row["review_item_id"],
            event_type=row["event_type"],
            actor=row["actor"],
            notes=row["notes"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=from_iso(row["created_at"]),
        )
