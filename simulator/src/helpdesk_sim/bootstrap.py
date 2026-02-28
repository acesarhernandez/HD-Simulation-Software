from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from helpdesk_sim.adapters.dry_run_gateway import DryRunGateway
from helpdesk_sim.adapters.gateway import ZammadGateway
from helpdesk_sim.adapters.zammad_http_gateway import ZammadHttpGateway
from helpdesk_sim.config import Settings
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.background_worker import BackgroundWorkers
from helpdesk_sim.services.catalog_service import CatalogService
from helpdesk_sim.services.generation_service import GenerationService
from helpdesk_sim.services.grading_service import GradingService
from helpdesk_sim.services.hint_service import HintService
from helpdesk_sim.services.poller_service import PollerService
from helpdesk_sim.services.report_service import ReportService
from helpdesk_sim.services.response_engine import (
    OllamaResponseEngine,
    ResponseEngine,
    RuleBasedResponseEngine,
)
from helpdesk_sim.services.scheduler_service import SchedulerService
from helpdesk_sim.services.session_service import SessionService


@dataclass(slots=True)
class Runtime:
    settings: Settings
    repository: SimulatorRepository
    catalog: CatalogService
    response_engine: ResponseEngine
    session_service: SessionService
    scheduler_service: SchedulerService
    poller_service: PollerService
    hint_service: HintService
    report_service: ReportService
    workers: BackgroundWorkers


def build_runtime(settings: Settings, cwd: Path) -> Runtime:
    db_path = settings.resolve_db_path(cwd)
    templates_dir = settings.resolve_templates_dir(cwd)

    repository = SimulatorRepository(db_path=db_path)
    repository.initialize()

    catalog = CatalogService(templates_dir=templates_dir)
    catalog.load()

    zammad_gateway = _build_zammad_gateway(settings)
    response_engine = _build_response_engine(settings)

    session_service = SessionService(repository=repository, catalog=catalog)
    generation_service = GenerationService(catalog=catalog)
    scheduler_service = SchedulerService(
        repository=repository,
        generation_service=generation_service,
        zammad_gateway=zammad_gateway,
    )
    grading_service = GradingService()
    poller_service = PollerService(
        repository=repository,
        zammad_gateway=zammad_gateway,
        response_engine=response_engine,
        grading_service=grading_service,
    )
    hint_service = HintService(repository=repository)
    report_service = ReportService(repository=repository)

    workers = BackgroundWorkers(
        scheduler_service=scheduler_service,
        poller_service=poller_service,
        scheduler_interval_seconds=settings.scheduler_interval_seconds,
        poll_interval_seconds=settings.poll_interval_seconds,
    )

    return Runtime(
        settings=settings,
        repository=repository,
        catalog=catalog,
        response_engine=response_engine,
        session_service=session_service,
        scheduler_service=scheduler_service,
        poller_service=poller_service,
        hint_service=hint_service,
        report_service=report_service,
        workers=workers,
    )


def _build_zammad_gateway(settings: Settings) -> ZammadGateway:
    if settings.use_dry_run:
        return DryRunGateway()
    return ZammadHttpGateway(
        base_url=settings.zammad_url,
        token=settings.zammad_token,
        verify_tls=settings.zammad_verify_tls,
        group_tier1=settings.zammad_group_tier1,
        group_tier2=settings.zammad_group_tier2,
        group_sysadmin=settings.zammad_group_sysadmin,
        customer_fallback_email=settings.zammad_customer_fallback_email,
    )


def _build_response_engine(settings: Settings) -> ResponseEngine:
    if settings.response_engine == "ollama":
        fallback_engine = (
            RuleBasedResponseEngine() if settings.ollama_fallback_to_rule_based else None
        )
        return OllamaResponseEngine(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
            fallback_engine=fallback_engine,
        )
    return RuleBasedResponseEngine()
