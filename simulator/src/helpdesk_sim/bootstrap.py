from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from helpdesk_sim.adapters.dry_run_gateway import DryRunGateway
from helpdesk_sim.adapters.gateway import ZammadGateway
from helpdesk_sim.adapters.knowledge_base import DisabledKnowledgeBaseProvider
from helpdesk_sim.adapters.zammad_http_gateway import ZammadHttpGateway
from helpdesk_sim.adapters.zammad_kb_provider import ZammadKnowledgeBaseProvider
from helpdesk_sim.config import Settings
from helpdesk_sim.repositories.sqlite_store import SimulatorRepository
from helpdesk_sim.services.background_worker import BackgroundWorkers
from helpdesk_sim.services.catalog_service import CatalogService
from helpdesk_sim.services.coaching_service import CoachingService
from helpdesk_sim.services.engine_control_client import (
    EngineControlClient,
    EngineReadinessCoordinator,
)
from helpdesk_sim.services.generation_service import GenerationService
from helpdesk_sim.services.god_mode_service import GodModeService
from helpdesk_sim.services.grading_service import GradingService
from helpdesk_sim.services.hint_service import HintService
from helpdesk_sim.services.investigation_service import InvestigationService
from helpdesk_sim.services.knowledge_matcher_service import KnowledgeMatcherService
from helpdesk_sim.services.knowledge_proposal_service import KnowledgeProposalService
from helpdesk_sim.services.knowledge_provider_service import KnowledgeProviderService
from helpdesk_sim.services.knowledge_review_service import KnowledgeReviewService
from helpdesk_sim.services.mentor_service import MentorService
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
    engine_control_client: EngineControlClient | None
    engine_readiness: EngineReadinessCoordinator
    response_engine: ResponseEngine
    session_service: SessionService
    scheduler_service: SchedulerService
    poller_service: PollerService
    hint_service: HintService
    investigation_service: InvestigationService
    mentor_service: MentorService
    coaching_service: CoachingService
    god_mode_service: GodModeService
    knowledge_provider_service: KnowledgeProviderService
    knowledge_proposal_service: KnowledgeProposalService
    knowledge_review_service: KnowledgeReviewService
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
    engine_control_client = _build_engine_control_client(settings)
    engine_readiness = EngineReadinessCoordinator(
        engine_client=engine_control_client,
        auto_wake_enabled=settings.engine_auto_wake,
        auto_wake_timeout_seconds=settings.engine_auto_wake_timeout_seconds,
    )
    response_engine = _build_response_engine(settings, engine_readiness)

    session_service = SessionService(repository=repository, catalog=catalog)
    generation_service = GenerationService(
        catalog=catalog,
        llm_enabled=settings.response_engine == "ollama",
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        rewrite_opening_tickets=settings.ollama_rewrite_opening_tickets,
        engine_readiness=engine_readiness,
    )
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
    investigation_service = InvestigationService()
    mentor_service = MentorService(
        llm_enabled=settings.response_engine == "ollama",
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        engine_readiness=engine_readiness,
    )
    coaching_service = CoachingService(
        llm_enabled=settings.response_engine == "ollama",
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        engine_readiness=engine_readiness,
    )
    god_mode_service = GodModeService(
        repository=repository,
        mentor_service=mentor_service,
        coaching_service=coaching_service,
        llm_enabled=settings.response_engine == "ollama",
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        default_attempt_first=settings.god_mode_default_attempt_first,
        reveal_mode=settings.god_mode_reveal_mode,
        engine_readiness=engine_readiness,
    )
    kb_provider = _build_knowledge_provider(settings)
    knowledge_provider_service = KnowledgeProviderService(
        repository=repository,
        provider=kb_provider,
        provider_name=settings.kb_provider,
    )
    knowledge_matcher = KnowledgeMatcherService()
    knowledge_proposal_service = KnowledgeProposalService(
        repository=repository,
        catalog=catalog,
        matcher=knowledge_matcher,
        provider_service=knowledge_provider_service,
        llm_enabled=settings.response_engine == "ollama",
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        min_score=settings.kb_min_score,
        engine_readiness=engine_readiness,
    )
    knowledge_review_service = KnowledgeReviewService(
        proposal_service=knowledge_proposal_service,
        provider_service=knowledge_provider_service,
        llm_enabled=settings.response_engine == "ollama",
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        review_required=settings.kb_review_required,
        engine_readiness=engine_readiness,
    )
    report_service = ReportService(repository=repository)

    if settings.kb_enabled and settings.kb_sync_on_start:
        try:
            knowledge_provider_service.sync_index()
        except Exception:
            pass

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
        engine_control_client=engine_control_client,
        engine_readiness=engine_readiness,
        response_engine=response_engine,
        session_service=session_service,
        scheduler_service=scheduler_service,
        poller_service=poller_service,
        hint_service=hint_service,
        investigation_service=investigation_service,
        mentor_service=mentor_service,
        coaching_service=coaching_service,
        god_mode_service=god_mode_service,
        knowledge_provider_service=knowledge_provider_service,
        knowledge_proposal_service=knowledge_proposal_service,
        knowledge_review_service=knowledge_review_service,
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


def _build_response_engine(
    settings: Settings,
    engine_readiness: EngineReadinessCoordinator,
) -> ResponseEngine:
    if settings.response_engine == "ollama":
        fallback_engine = (
            RuleBasedResponseEngine() if settings.ollama_fallback_to_rule_based else None
        )
        return OllamaResponseEngine(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
            fallback_engine=fallback_engine,
            engine_readiness=engine_readiness,
        )
    return RuleBasedResponseEngine()


def _build_engine_control_client(settings: Settings) -> EngineControlClient | None:
    url = settings.engine_control_url.strip()
    token = settings.engine_control_api_key.strip()
    if not url or not token:
        return None
    return EngineControlClient(
        base_url=url,
        api_key=token,
    )


def _build_knowledge_provider(settings: Settings):
    if not settings.kb_enabled:
        return DisabledKnowledgeBaseProvider(reason="Knowledge base review mode is disabled.")
    if settings.kb_provider != "zammad":
        return DisabledKnowledgeBaseProvider(
            reason=f"Unsupported knowledge base provider '{settings.kb_provider}'."
        )
    if not settings.zammad_url.strip() or not settings.zammad_token.strip():
        return DisabledKnowledgeBaseProvider(reason="Zammad URL and token are required for KB sync.")
    if (
        settings.kb_zammad_kb_id <= 0
        or settings.kb_zammad_locale_id <= 0
        or settings.kb_zammad_default_category_id <= 0
    ):
        return DisabledKnowledgeBaseProvider(
            reason="KB ID, locale ID, and default category ID are required for Zammad KB."
        )
    return ZammadKnowledgeBaseProvider(
        base_url=settings.zammad_url,
        token=settings.zammad_token,
        knowledge_base_id=settings.kb_zammad_kb_id,
        locale_id=settings.kb_zammad_locale_id,
        default_category_id=settings.kb_zammad_default_category_id,
        publish_mode=settings.kb_zammad_publish_mode,
        verify_tls=settings.zammad_verify_tls,
    )
