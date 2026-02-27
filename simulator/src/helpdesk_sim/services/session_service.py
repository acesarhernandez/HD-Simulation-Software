from __future__ import annotations

from datetime import timedelta

from helpdesk_sim.domain.models import SessionRecord
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.catalog_service import CatalogService
from helpdesk_sim.utils import utc_now


class SessionService:
    def __init__(self, repository: SimulatorRepository, catalog: CatalogService) -> None:
        self.repository = repository
        self.catalog = catalog

    def list_profiles(self) -> list[str]:
        return self.catalog.list_profiles()

    def list_profile_definitions(self) -> list[dict]:
        return [
            profile.model_dump(mode="json")
            for profile in self.catalog.list_profile_definitions()
        ]

    def clock_in(self, profile_name: str) -> SessionRecord:
        profile = self.catalog.get_profile(profile_name)
        started_at = utc_now()
        ends_at = started_at + timedelta(hours=profile.duration_hours)
        next_window = started_at
        return self.repository.create_session(
            profile_name=profile.name,
            started_at=started_at,
            ends_at=ends_at,
            next_window_at=next_window,
            config=profile.model_dump(mode="json"),
        )

    def clock_out(self, session_id: str) -> SessionRecord:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ValueError(f"session '{session_id}' does not exist")
        self.repository.complete_session(session_id)
        updated = self.repository.get_session(session_id)
        if updated is None:
            raise RuntimeError("failed to load updated session")
        return updated

    def clock_out_all(self) -> list[SessionRecord]:
        active = self.repository.list_active_sessions()
        updated: list[SessionRecord] = []
        for session in active:
            self.repository.complete_session(session.id)
            refreshed = self.repository.get_session(session.id)
            if refreshed is not None:
                updated.append(refreshed)
        return updated

    def get_session(self, session_id: str) -> SessionRecord:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ValueError(f"session '{session_id}' does not exist")
        return session
