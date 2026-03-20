from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from helpdesk_sim import __version__
from helpdesk_sim.domain.models import (
    ClockInRequest,
    GodModeAdvanceRequest,
    GodModeAttemptRequest,
    GodModeDraftRequest,
    GodModeStartRequest,
    HintRequest,
    KnowledgeReviewDecisionRequest,
    KnowledgeReviewStatus,
    KnowledgeRevisionRequest,
    ManualTicketRequest,
    MentorRequest,
    ScoreMode,
)
from helpdesk_sim.services.engine_control_client import (
    is_engine_ready_state,
    normalize_engine_state,
)
from helpdesk_sim.services.wake_on_lan import (
    is_tcp_endpoint_reachable,
    mask_mac_address,
    send_magic_packet,
)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/v1/runtime/response-engine")
def get_response_engine_status(request: Request) -> dict[str, object]:
    runtime = request.app.state.runtime
    status = runtime.response_engine.describe_status()
    status.update(_engine_runtime_status(runtime))
    status["english_summary"] = _response_engine_summary(status)
    return status


@router.post("/v1/runtime/wake-llm-host")
def wake_llm_host(request: Request) -> dict[str, object]:
    runtime = request.app.state.runtime
    settings = runtime.settings
    engine_controller = runtime.engine_control_client
    if engine_controller is not None and engine_controller.is_configured():
        try:
            payload = engine_controller.wake()
            runtime.engine_readiness.mark_wake_requested()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"failed to send wake request via engine controller: {exc}",
            ) from exc

        state = normalize_engine_state(payload)
        label = settings.llm_host_label
        summary = str(payload.get("english_summary") or "").strip()
        if not summary:
            summary = f"Wake request sent via engine controller for {label}."

        return {
            "wake_sent": bool(payload.get("wake_sent", True)),
            "packet_bytes": int(payload.get("packet_bytes", 0) or 0),
            "llm_host_label": label,
            "llm_host_mac_masked": payload.get("llm_host_mac_masked"),
            "wake_on_lan_enabled": True,
            "wake_on_lan_ready": True,
            "broadcast_ip": payload.get("broadcast_ip", ""),
            "port": int(payload.get("port", 0) or 0),
            "engine_control_mode": "controller",
            "engine_state": state,
            "controller_payload": payload,
            "english_summary": summary,
        }

    if not settings.llm_host_wol_enabled:
        raise HTTPException(status_code=400, detail="Wake-on-LAN is disabled for the LLM host")
    if not settings.llm_host_mac.strip():
        raise HTTPException(status_code=400, detail="LLM host MAC address is not configured")

    try:
        packet_bytes = send_magic_packet(
            mac_address=settings.llm_host_mac,
            broadcast_ip=settings.llm_host_wol_broadcast_ip,
            port=settings.llm_host_wol_port,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid LLM host MAC address: {exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"failed to send Wake-on-LAN packet: {exc}",
        ) from exc

    return {
        "wake_sent": True,
        "packet_bytes": packet_bytes,
        "llm_host_label": settings.llm_host_label,
        "llm_host_mac_masked": mask_mac_address(settings.llm_host_mac),
        "wake_on_lan_enabled": True,
        "wake_on_lan_ready": True,
        "broadcast_ip": settings.llm_host_wol_broadcast_ip,
        "port": settings.llm_host_wol_port,
        "english_summary": (
            f"Wake signal sent to {settings.llm_host_label} "
            f"({mask_mac_address(settings.llm_host_mac)})."
        ),
    }


@router.get("/v1/profiles")
def list_profiles(request: Request) -> dict:
    runtime = request.app.state.runtime
    return {
        "profiles": runtime.session_service.list_profiles(),
        "definitions": runtime.session_service.list_profile_definitions(),
    }


@router.get("/v1/catalog")
def get_catalog(request: Request) -> dict:
    runtime = request.app.state.runtime
    scenarios = runtime.catalog.list_scenarios()
    personas = runtime.catalog.list_personas()
    return {
        "ticket_types": runtime.catalog.list_ticket_types(),
        "departments": runtime.catalog.list_departments(),
        "scenarios": [
            {
                "id": scenario.id,
                "title": scenario.title,
                "ticket_type": scenario.ticket_type,
                "tier": scenario.tier.value,
                "persona_roles": scenario.persona_roles,
                "tags": scenario.tags,
            }
            for scenario in scenarios
        ],
        "personas": [persona.model_dump(mode="json") for persona in personas],
    }


@router.get("/v1/knowledge-articles")
def list_knowledge_articles(request: Request) -> dict[str, list[dict]]:
    runtime = request.app.state.runtime
    articles = runtime.catalog.list_knowledge_articles()
    return {"articles": [article.model_dump(mode="json") for article in articles]}


@router.get("/v1/kb/providers/status")
def get_kb_provider_status(request: Request) -> dict[str, object]:
    runtime = request.app.state.runtime
    status = runtime.knowledge_provider_service.status()
    if not runtime.settings.kb_enabled:
        status["english_summary"] = "KB review mode is disabled."
    elif not bool(status.get("ready")):
        status["english_summary"] = str(status.get("reason") or "KB provider is not ready.")
    else:
        status["english_summary"] = (
            f"{status.get('provider', 'KB provider')} is ready. "
            f"Cached articles: {status.get('cached_article_count', 0)}."
        )
    return status


@router.post("/v1/kb/sync")
def sync_kb_provider(request: Request) -> dict[str, object]:
    runtime = request.app.state.runtime
    if not runtime.settings.kb_enabled:
        raise HTTPException(status_code=400, detail="KB review mode is disabled")
    try:
        return runtime.knowledge_provider_service.sync_index()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/v1/kb/review-items")
def list_kb_review_items(
    request: Request,
    status: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    source_ticket_id: str | None = Query(default=None),
) -> dict[str, object]:
    runtime = request.app.state.runtime
    parsed_status = None
    if status:
        try:
            parsed_status = KnowledgeReviewStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid KB review status '{status}'") from exc
    payload = runtime.knowledge_review_service.list_review_items(
        status=parsed_status,
        provider=provider,
        source_ticket_id=source_ticket_id,
    )
    payload["english_summary"] = f"{payload['count']} KB review item(s) loaded."
    return payload


@router.get("/v1/kb/review-items/{review_item_id}")
def get_kb_review_item(request: Request, review_item_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    try:
        detail = runtime.knowledge_review_service.get_review_detail(review_item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    detail["english_summary"] = f"Loaded KB review item {review_item_id[:8]}."
    return detail


@router.post("/v1/kb/review-items/{review_item_id}/revise")
def revise_kb_review_item(
    request: Request,
    review_item_id: str,
    payload: KnowledgeRevisionRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    try:
        return runtime.knowledge_review_service.revise_review_item(review_item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/kb/review-items/{review_item_id}/approve")
def approve_kb_review_item(
    request: Request,
    review_item_id: str,
    payload: KnowledgeReviewDecisionRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    try:
        return runtime.knowledge_review_service.approve_review_item(review_item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/kb/review-items/{review_item_id}/publish")
def publish_kb_review_item(request: Request, review_item_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    try:
        return runtime.knowledge_review_service.publish_review_item(review_item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/kb/review-items/{review_item_id}/reject")
def reject_kb_review_item(
    request: Request,
    review_item_id: str,
    payload: KnowledgeReviewDecisionRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    try:
        return runtime.knowledge_review_service.reject_review_item(review_item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/sessions")
def list_sessions(request: Request) -> dict[str, list[dict]]:
    runtime = request.app.state.runtime
    sessions = runtime.repository.list_active_sessions()
    payload: list[dict] = []
    for session in sessions:
        tickets = runtime.repository.list_tickets_for_session(session.id)
        payload.append(
            {
                **session.model_dump(mode="json"),
                "ticket_count": len(tickets),
            }
        )
    return {"sessions": payload}


@router.post("/v1/sessions/clock-in")
def clock_in(request: Request, payload: ClockInRequest) -> dict:
    runtime = request.app.state.runtime
    try:
        session = runtime.session_service.clock_in(payload.profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.model_dump(mode="json")


@router.post("/v1/sessions/{session_id}/clock-out")
def clock_out(request: Request, session_id: str) -> dict:
    runtime = request.app.state.runtime
    try:
        session = runtime.session_service.clock_out(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.model_dump(mode="json")


@router.post("/v1/sessions/clock-out-all")
def clock_out_all(request: Request) -> dict[str, object]:
    runtime = request.app.state.runtime
    sessions = runtime.session_service.clock_out_all()
    session_ids = [session.id for session in sessions]
    return {
        "clocked_out": len(sessions),
        "session_ids": session_ids,
        "english_summary": (
            f"Clocked out {len(sessions)} active session(s)."
            if sessions
            else "No active sessions were running."
        ),
    }


@router.get("/v1/sessions/{session_id}")
def get_session(request: Request, session_id: str) -> dict:
    runtime = request.app.state.runtime
    session = runtime.repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    tickets = runtime.repository.list_tickets_for_session(session_id)
    return {
        "session": session.model_dump(mode="json"),
        "tickets": [ticket.model_dump(mode="json") for ticket in tickets],
    }


@router.get("/v1/tickets/{ticket_id}")
def get_ticket(request: Request, ticket_id: str) -> dict:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    interactions = runtime.repository.list_interactions(ticket_id)
    return {
        "ticket": ticket.model_dump(mode="json"),
        "interactions": [row.model_dump(mode="json") for row in interactions],
    }


@router.get("/v1/tickets/{ticket_id}/investigation-checks")
def get_ticket_investigation_checks(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    payload = runtime.investigation_service.build_ticket_report(ticket)
    payload["english_summary"] = (
        f"Deterministic investigation checks loaded for ticket {ticket_id[:8]}."
    )
    return payload


@router.post("/v1/tickets/{ticket_id}/knowledge-draft")
def generate_knowledge_draft(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    interactions = runtime.repository.list_interactions(ticket_id)
    hidden = ticket.hidden_truth or {}

    if ticket.status.value != "closed":
        return {
            "ticket_id": ticket_id,
            "ready": False,
            "english_summary": "Close this ticket first, then generate a KB draft from the completed case.",
            "markdown": "",
        }

    markdown = _build_kb_markdown(ticket=ticket, hidden=hidden, interactions=interactions)
    return {
        "ticket_id": ticket_id,
        "ready": True,
        "english_summary": "KB draft generated. Review and copy into your knowledge base.",
        "markdown": markdown,
    }


@router.post("/v1/tickets/{ticket_id}/kb/propose")
def propose_knowledge_article(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    if not runtime.settings.kb_enabled:
        raise HTTPException(status_code=400, detail="KB review mode is disabled")
    try:
        return runtime.knowledge_proposal_service.propose_for_ticket(ticket_id)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/tickets/{ticket_id}/coach")
def generate_ticket_coaching(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    if ticket.status.value != "closed" or not ticket.score:
        return {
            "ticket_id": ticket_id,
            "ready": False,
            "coaching_note": "",
            "deterministic_note": "",
            "strengths": [],
            "focus_areas": [],
            "documentation_critique": "",
            "professionalism_critique": "",
            "llm_used": False,
            "last_error": None,
            "english_summary": "Close the ticket first so the simulator has a final grade to coach against.",
        }

    interactions = runtime.repository.list_interactions(ticket_id)
    payload = runtime.coaching_service.generate_ticket_coaching(ticket=ticket, interactions=interactions)
    return {
        "ticket_id": ticket_id,
        "ready": True,
        **payload,
    }


@router.post("/v1/tickets/{ticket_id}/mentor")
def request_mentor_guidance(
    request: Request,
    ticket_id: str,
    payload: MentorRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    interactions = runtime.repository.list_interactions(ticket_id)
    response = runtime.mentor_service.request_guidance(
        ticket=ticket,
        interactions=interactions,
        analyst_message=payload.message,
    )
    runtime.repository.add_interaction(
        ticket_id=ticket_id,
        actor="mentor",
        body=str(response.get("mentor_reply", "")).strip() or "Mentor guidance generated.",
        metadata={"event": "mentor", "analyst_message": payload.message},
    )
    return {
        "ticket_id": ticket_id,
        **response,
    }


@router.post("/v1/tickets/{ticket_id}/close")
def close_ticket(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if ticket.status.value == "closed":
        return {
            "ticket_id": ticket_id,
            "closed": False,
            "english_summary": f"Ticket {ticket_id} is already closed.",
        }

    manual_score = {
        "manual_close": True,
        "reason": "closed from simulator dashboard",
        "score": {
            "troubleshooting": 0,
            "correctness": 0,
            "communication": 0,
            "documentation": 0,
            "sla": 0,
            "escalation": 0,
            "hint_penalty": 0,
            "total": 0,
        },
        "metrics": {},
        "missed_checks": [],
    }
    manual_score = runtime.god_mode_service.tag_score_payload(ticket, manual_score)
    runtime.repository.close_ticket(
        ticket_id=ticket_id,
        score=manual_score,
    )
    return {
        "ticket_id": ticket_id,
        "closed": True,
        "english_summary": f"Ticket {ticket_id} was marked closed in simulator.",
    }


@router.delete("/v1/tickets/{ticket_id}")
def delete_ticket(
    request: Request,
    ticket_id: str,
    fallback_close_on_delete_failure: bool = Query(default=False),
) -> dict[str, object]:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="ticket not found in simulator (use local ticket UUID)",
        )

    zammad_deleted = False
    zammad_closed_fallback = False
    if ticket.zammad_ticket_id is not None:
        try:
            zammad_deleted = bool(
                runtime.scheduler_service.zammad_gateway.delete_ticket(ticket.zammad_ticket_id)
            )
        except Exception as exc:
            if not fallback_close_on_delete_failure:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"failed to delete Zammad ticket {ticket.zammad_ticket_id}: {exc}"
                    ),
                ) from exc
            try:
                zammad_closed_fallback = bool(
                    runtime.scheduler_service.zammad_gateway.close_ticket(ticket.zammad_ticket_id)
                )
            except Exception as close_exc:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"failed to delete Zammad ticket {ticket.zammad_ticket_id}: {exc}. "
                        f"fallback close also failed: {close_exc}"
                    ),
                ) from close_exc

    deleted = runtime.repository.delete_ticket(ticket_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="ticket not found in simulator (use local ticket UUID)",
        )

    summary = f"Ticket {ticket_id} was deleted from simulator data."
    if ticket.zammad_ticket_id is not None:
        if zammad_deleted:
            summary = (
                f"Ticket {ticket_id} was deleted from simulator data "
                f"and Zammad ticket {ticket.zammad_ticket_id}."
            )
        else:
            summary = (
                f"Ticket {ticket_id} was deleted locally. "
                f"Zammad ticket {ticket.zammad_ticket_id} deletion status is unknown."
            )
        if zammad_closed_fallback:
            summary = (
                f"Ticket {ticket_id} was removed from simulator data. "
                f"Zammad ticket {ticket.zammad_ticket_id} could not be deleted and was closed instead."
            )

    return {
        "ticket_id": ticket_id,
        "deleted": True,
        "zammad_ticket_id": ticket.zammad_ticket_id,
        "zammad_deleted": zammad_deleted,
        "zammad_closed_fallback": zammad_closed_fallback,
        "english_summary": summary,
    }


@router.get("/v1/tickets/{ticket_id}/knowledge-articles")
def get_ticket_knowledge_articles(request: Request, ticket_id: str) -> dict[str, list[dict]]:
    runtime = request.app.state.runtime
    ticket = runtime.repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    article_ids = ticket.hidden_truth.get("knowledge_article_ids", [])
    if not isinstance(article_ids, list):
        article_ids = []
    articles = runtime.catalog.get_knowledge_articles([str(item) for item in article_ids])

    return {"articles": [article.model_dump(mode="json") for article in articles]}


@router.post("/v1/hints")
def request_hint(request: Request, payload: HintRequest) -> dict:
    runtime = request.app.state.runtime
    try:
        hint = runtime.hint_service.request_hint(payload.ticket_id, payload.level)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = hint.model_dump(mode="json")
    response["english_summary"] = (
        f"{payload.level.value.replace('_', ' ').title()} hint: {hint.hint} "
        f"(Penalty: +{hint.penalty_applied} points)"
    )
    return response


@router.post("/v1/tickets/generate")
def generate_manual_tickets(request: Request, payload: ManualTicketRequest) -> dict:
    runtime = request.app.state.runtime
    session_id = payload.session_id
    if not session_id:
        active_sessions = runtime.repository.list_active_sessions()
        if not active_sessions:
            raise HTTPException(status_code=400, detail="no active session found")
        latest_session = max(active_sessions, key=lambda session: session.started_at)
        session_id = latest_session.id

    created: list[dict] = []
    try:
        for _ in range(payload.count):
            record = runtime.scheduler_service.create_manual_ticket(
                session_id=session_id,
                forced_tier=payload.tier,
                forced_ticket_type=payload.ticket_type,
                forced_department=payload.department,
                forced_persona_id=payload.persona_id,
                forced_scenario_id=payload.scenario_id,
                required_tags=payload.required_tags,
            )
            created.append(record.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "session_id": session_id,
        "requested_count": payload.count,
        "created_count": len(created),
        "tickets": created,
    }


@router.post("/v1/sessions/{session_id}/tickets/close-all")
def close_all_tickets_for_session(request: Request, session_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    session = runtime.repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    closed = runtime.repository.close_open_tickets_for_session(
        session_id=session_id,
        score={
            "manual_close": True,
            "reason": "bulk close from simulator dashboard",
            "score": {
                "troubleshooting": 0,
                "correctness": 0,
                "communication": 0,
                "documentation": 0,
                "sla": 0,
                "escalation": 0,
                "hint_penalty": 0,
                "total": 0,
            },
            "metrics": {},
            "missed_checks": [],
            "meta": {
                "score_mode": ScoreMode.practice.value,
                "god_mode_used": False,
            },
        },
    )
    return {
        "session_id": session_id,
        "closed_count": closed,
        "english_summary": f"Closed {closed} open ticket(s) in this session.",
    }


@router.delete("/v1/sessions/{session_id}/tickets")
def delete_all_tickets_for_session(
    request: Request,
    session_id: str,
    fallback_close_on_delete_failure: bool = Query(default=False),
) -> dict[str, object]:
    runtime = request.app.state.runtime
    session = runtime.repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    tickets = runtime.repository.list_tickets_for_session(session_id)
    zammad_deleted_count = 0
    zammad_closed_fallback_count = 0
    zammad_attempted = 0
    zammad_failures: list[str] = []
    for ticket in tickets:
        if ticket.zammad_ticket_id is None:
            continue
        zammad_attempted += 1
        try:
            deleted = runtime.scheduler_service.zammad_gateway.delete_ticket(ticket.zammad_ticket_id)
            if deleted:
                zammad_deleted_count += 1
        except Exception as exc:
            if not fallback_close_on_delete_failure:
                zammad_failures.append(f"{ticket.zammad_ticket_id}: {exc}")
                continue
            try:
                closed = runtime.scheduler_service.zammad_gateway.close_ticket(ticket.zammad_ticket_id)
                if closed:
                    zammad_closed_fallback_count += 1
                else:
                    zammad_failures.append(
                        f"{ticket.zammad_ticket_id}: delete failed ({exc}); fallback close returned false"
                    )
            except Exception as close_exc:
                zammad_failures.append(
                    f"{ticket.zammad_ticket_id}: delete failed ({exc}); fallback close failed ({close_exc})"
                )

    if zammad_failures:
        failure_list = "; ".join(zammad_failures[:6])
        raise HTTPException(
            status_code=502,
            detail=(
                "failed to delete one or more Zammad tickets before local cleanup: "
                f"{failure_list}"
            ),
        )

    deleted = runtime.repository.delete_tickets_for_session(session_id=session_id)
    summary = f"Deleted {deleted} ticket(s) from simulator data for this session."
    if zammad_attempted:
        summary = (
            f"Deleted {deleted} ticket(s) from simulator data and "
            f"{zammad_deleted_count}/{zammad_attempted} linked Zammad ticket(s)."
        )
    if zammad_closed_fallback_count:
        summary += (
            f" {zammad_closed_fallback_count} ticket(s) were closed in Zammad as fallback "
            "when delete was blocked."
        )
    return {
        "session_id": session_id,
        "deleted_count": deleted,
        "zammad_deleted_count": zammad_deleted_count,
        "zammad_closed_fallback_count": zammad_closed_fallback_count,
        "zammad_attempted": zammad_attempted,
        "english_summary": summary,
    }


@router.post("/v1/scheduler/run-once")
async def run_scheduler_once(request: Request) -> dict[str, int]:
    runtime = request.app.state.runtime
    return await runtime.workers.run_scheduler_once()


@router.post("/v1/poller/run-once")
async def run_poller_once(request: Request) -> dict[str, int]:
    runtime = request.app.state.runtime
    return await runtime.workers.run_poller_once()


@router.get("/v1/god/config")
def get_god_config(request: Request) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    settings = runtime.settings
    return {
        "enabled": bool(settings.god_mode_enabled),
        "key_required": bool(settings.god_mode_access_key.strip()),
        "default_attempt_first": bool(settings.god_mode_default_attempt_first),
        "reveal_mode": settings.god_mode_reveal_mode,
        "separate_reports": bool(settings.god_mode_separate_reports),
        "phases": runtime.god_mode_service.list_phases(),
        "english_summary": "God mode configuration loaded.",
    }


@router.post("/v1/god/tickets/{ticket_id}/start")
def start_god_ticket(
    request: Request,
    ticket_id: str,
    payload: GodModeStartRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        data = runtime.god_mode_service.start_ticket(
            ticket_id=ticket_id,
            attempt_first=payload.attempt_first,
        )
        return data
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/god/tickets/{ticket_id}/walkthrough")
def get_god_walkthrough(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.get_walkthrough(ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v1/god/tickets/{ticket_id}/phase/{phase_key}/attempt")
def submit_god_attempt(
    request: Request,
    ticket_id: str,
    phase_key: str,
    payload: GodModeAttemptRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.submit_attempt(
            ticket_id=ticket_id,
            phase_key=phase_key,
            text=payload.text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/god/tickets/{ticket_id}/phase/{phase_key}/advance")
def advance_god_phase(
    request: Request,
    ticket_id: str,
    phase_key: str,
    payload: GodModeAdvanceRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.advance_phase(
            ticket_id=ticket_id,
            phase_key=phase_key,
            note=payload.note,
            force=payload.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/god/tickets/{ticket_id}/reveal-truth")
def reveal_god_truth(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.reveal_truth(ticket_id=ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v1/god/tickets/{ticket_id}/draft/public-reply")
def god_public_reply_draft(
    request: Request,
    ticket_id: str,
    payload: GodModeDraftRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.generate_draft(
            ticket_id=ticket_id,
            draft_type="public_reply",
            instruction=payload.instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/god/tickets/{ticket_id}/draft/internal-note")
def god_internal_note_draft(
    request: Request,
    ticket_id: str,
    payload: GodModeDraftRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.generate_draft(
            ticket_id=ticket_id,
            draft_type="internal_note",
            instruction=payload.instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/god/tickets/{ticket_id}/draft/escalation-handoff")
def god_escalation_handoff_draft(
    request: Request,
    ticket_id: str,
    payload: GodModeDraftRequest,
) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.generate_draft(
            ticket_id=ticket_id,
            draft_type="escalation_handoff",
            instruction=payload.instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/god/tickets/{ticket_id}/replay")
def get_god_replay(request: Request, ticket_id: str) -> dict[str, object]:
    runtime = request.app.state.runtime
    _require_god_access(request)
    try:
        return runtime.god_mode_service.build_replay(ticket_id=ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/reports/daily")
def report_daily(request: Request) -> dict:
    runtime = request.app.state.runtime
    score_mode = ScoreMode.practice.value if runtime.settings.god_mode_separate_reports else None
    report = runtime.report_service.generate("daily", score_mode=score_mode)
    report["english_summary"] = _report_summary(report_type="daily", report=report)
    return report


@router.get("/v1/reports/weekly")
def report_weekly(request: Request) -> dict:
    runtime = request.app.state.runtime
    score_mode = ScoreMode.practice.value if runtime.settings.god_mode_separate_reports else None
    report = runtime.report_service.generate("weekly", score_mode=score_mode)
    report["english_summary"] = _report_summary(report_type="weekly", report=report)
    return report


@router.get("/v1/god/reports/daily")
def report_god_daily(request: Request) -> dict:
    runtime = request.app.state.runtime
    _require_god_access(request)
    score_mode = ScoreMode.guided_training.value if runtime.settings.god_mode_separate_reports else None
    report = runtime.report_service.generate("daily", score_mode=score_mode)
    report["english_summary"] = _report_summary(report_type="daily", report=report)
    return report


@router.get("/v1/god/reports/weekly")
def report_god_weekly(request: Request) -> dict:
    runtime = request.app.state.runtime
    _require_god_access(request)
    score_mode = ScoreMode.guided_training.value if runtime.settings.god_mode_separate_reports else None
    report = runtime.report_service.generate("weekly", score_mode=score_mode)
    report["english_summary"] = _report_summary(report_type="weekly", report=report)
    return report


def _require_god_access(request: Request) -> None:
    runtime = request.app.state.runtime
    settings = runtime.settings
    if not settings.god_mode_enabled:
        raise HTTPException(status_code=404, detail="Not Found")

    required_key = settings.god_mode_access_key.strip()
    if not required_key:
        return

    provided = request.headers.get("X-God-Key", "").strip()
    if not provided or provided != required_key:
        raise HTTPException(status_code=404, detail="Not Found")


def _report_summary(report_type: str, report: dict) -> str:
    label = "Daily" if report_type == "daily" else "Weekly"
    mode = str(report.get("score_mode") or "all")
    mode_label = "practice" if mode == "practice" else "guided training" if mode == "guided_training" else "all"
    closed = int(report.get("tickets_closed", 0))
    avg_score = float(report.get("average_score", 0))
    avg_first_response = float(report.get("average_first_response_minutes", 0))
    avg_resolution = float(report.get("average_resolution_minutes", 0))
    sla_miss = float(report.get("sla_miss_rate", 0)) * 100.0
    summary = (
        f"{label} performance ({mode_label}): {closed} tickets closed. "
        f"Average score {avg_score:.2f}, first response {avg_first_response:.2f} minutes, "
        f"resolution {avg_resolution:.2f} minutes, SLA miss rate {sla_miss:.2f}%."
    )
    comparison = report.get("comparison")
    if isinstance(comparison, dict) and "score_delta" in comparison:
        delta = float(comparison["score_delta"])
        direction = "up" if delta >= 0 else "down"
        summary += f" Score trend: {direction} {abs(delta):.2f} vs previous {label.lower()} report."
    return summary


def _response_engine_summary(status: dict[str, object]) -> str:
    configured = str(status.get("configured_engine", "unknown")).replace("_", " ")
    active = str(status.get("active_mode", "unknown")).replace("_", " ")
    if configured == "rule based":
        count = int(status.get("generated_reply_count", 0))
        summary = f"Rule-based response engine is active. Generated replies: {count}."
        wake_summary = _wake_summary(status)
        if wake_summary:
            summary += f" {wake_summary}"
        return summary

    success = int(status.get("successful_llm_reply_count", 0))
    fallback = int(status.get("fallback_reply_count", 0))
    summary = (
        f"Ollama response engine is configured. Current mode: {active}. "
        f"LLM replies: {success}. Fallback replies: {fallback}."
    )
    last_error = status.get("last_error")
    if last_error:
        summary += f" Last LLM error: {last_error}."
    wake_summary = _wake_summary(status)
    if wake_summary:
        summary += f" {wake_summary}"
    return summary


def _legacy_wake_on_lan_status(settings) -> dict[str, object]:
    reachable, endpoint_host, endpoint_port = is_tcp_endpoint_reachable(settings.ollama_url)
    mac = settings.llm_host_mac.strip()
    masked_mac = None
    mac_valid = False
    if mac:
        try:
            masked_mac = mask_mac_address(mac)
            mac_valid = True
        except ValueError:
            masked_mac = None
            mac_valid = False
    ready = bool(settings.llm_host_wol_enabled and mac_valid)
    return {
        "llm_host_label": settings.llm_host_label,
        "llm_host_reachable": reachable,
        "llm_host_endpoint_host": endpoint_host,
        "llm_host_endpoint_port": endpoint_port,
        "wake_on_lan_enabled": settings.llm_host_wol_enabled,
        "wake_on_lan_ready": ready,
        "llm_host_mac_masked": masked_mac,
        "llm_host_mac_valid": mac_valid,
        "llm_host_wol_broadcast_ip": settings.llm_host_wol_broadcast_ip,
        "llm_host_wol_port": settings.llm_host_wol_port,
    }


def _engine_runtime_status(runtime) -> dict[str, object]:
    settings = runtime.settings
    endpoint_reachable, endpoint_host, endpoint_port = is_tcp_endpoint_reachable(settings.ollama_url)
    controller = runtime.engine_control_client
    if controller is None or not controller.is_configured():
        status = _legacy_wake_on_lan_status(settings)
        status["engine_control_mode"] = "legacy_wol"
        status["engine_control_configured"] = False
        status["engine_state"] = "ready" if status.get("llm_host_reachable") else "offline"
        status["engine_ready"] = bool(status.get("llm_host_reachable"))
        return status

    status: dict[str, object] = {
        "engine_control_mode": "controller",
        "engine_control_configured": True,
        "engine_control_url": settings.engine_control_url,
        "engine_auto_wake": settings.engine_auto_wake,
        "engine_auto_wake_timeout_seconds": settings.engine_auto_wake_timeout_seconds,
        "llm_host_label": settings.llm_host_label,
        "llm_host_endpoint_host": endpoint_host,
        "llm_host_endpoint_port": endpoint_port,
        "llm_host_wol_broadcast_ip": settings.llm_host_wol_broadcast_ip,
        "llm_host_wol_port": settings.llm_host_wol_port,
        "wake_on_lan_enabled": True,
        "wake_on_lan_ready": True,
        "llm_host_mac_masked": None,
        "llm_host_mac_valid": True,
        "llm_host_reachable": endpoint_reachable,
        "engine_state": "unknown",
        "engine_ready": False,
    }

    try:
        controller_payload = controller.get_status()
    except Exception as exc:
        status["engine_control_error"] = str(exc)
        status["wake_on_lan_ready"] = False
        return status

    state = normalize_engine_state(controller_payload)
    ready = bool(controller_payload.get("ready")) or is_engine_ready_state(state)
    status.update(
        {
            "engine_state": state,
            "engine_ready": ready,
            "llm_host_reachable": ready or endpoint_reachable,
            "controller_payload": controller_payload,
        }
    )
    if "llm_host_mac_masked" in controller_payload:
        status["llm_host_mac_masked"] = controller_payload.get("llm_host_mac_masked")
    if "wake_supported" in controller_payload:
        status["wake_on_lan_ready"] = bool(controller_payload.get("wake_supported"))
    return status


def _wake_summary(status: dict[str, object]) -> str:
    if str(status.get("engine_control_mode")) == "controller":
        label = str(status.get("llm_host_label", "LLM engine"))
        state = str(status.get("engine_state", "unknown")).replace("_", " ")
        if status.get("engine_control_error"):
            return (
                f"Engine controller status is unavailable: {status['engine_control_error']}. "
                "Manual wake may still be possible."
            )
        if state == "ready":
            return f"Engine controller reports {label} is ready."
        if state == "pc online":
            return f"Engine controller reports {label} is online but Ollama is not ready yet."
        if state == "waking":
            return f"Engine controller reports {label} is waking."
        if state == "offline":
            return f"Engine controller reports {label} is offline."
        return f"Engine controller state for {label}: {state}."

    enabled = bool(status.get("wake_on_lan_enabled"))
    ready = bool(status.get("wake_on_lan_ready"))
    reachable = bool(status.get("llm_host_reachable"))
    label = str(status.get("llm_host_label", "LLM host"))
    host = status.get("llm_host_endpoint_host")
    port = status.get("llm_host_endpoint_port")
    endpoint = f"{host}:{port}" if host and port else None
    if reachable:
        if endpoint:
            return f"{label} is reachable at {endpoint}. Wake-on-LAN is optional right now."
        return f"{label} is reachable. Wake-on-LAN is optional right now."
    if ready:
        if endpoint:
            return f"{label} is not reachable at {endpoint}. Wake-on-LAN is ready."
        return f"{label} is not reachable. Wake-on-LAN is ready."
    if enabled:
        return f"Wake-on-LAN is enabled for {label}, but MAC configuration is incomplete or invalid."
    return f"Wake-on-LAN is off for {label}."


def _build_kb_markdown(ticket, hidden: dict, interactions) -> str:
    expected_checks = hidden.get("expected_agent_checks", [])
    resolution_steps = hidden.get("resolution_steps", [])
    root_cause = str(hidden.get("root_cause", "Root cause not documented.")).strip()
    ticket_type = str(hidden.get("ticket_type", "general")).strip()
    scenario_id = str(hidden.get("scenario_id", ticket.scenario_id)).strip()
    persona = hidden.get("persona", {}) if isinstance(hidden.get("persona", {}), dict) else {}

    agent_messages = [row.body.strip() for row in interactions if row.actor == "agent" and row.body.strip()]
    customer_messages = [
        row.body.strip() for row in interactions if row.actor == "customer" and row.body.strip()
    ]
    issue_summary = customer_messages[0] if customer_messages else ticket.subject

    recent_agent_notes = "\n".join([f"- {line}" for line in agent_messages[-5:]]) or "- No agent notes captured."
    checks_block = "\n".join([f"- {item}" for item in expected_checks]) or "- Not specified."
    steps_block = "\n".join([f"- {item}" for item in resolution_steps]) or "- Not specified."

    return (
        f"# {ticket.subject}\n\n"
        "## Summary\n"
        f"- Ticket Type: {ticket_type}\n"
        f"- Tier: {ticket.tier.value}\n"
        f"- Priority: {ticket.priority.value}\n"
        f"- Scenario ID: {scenario_id}\n"
        f"- Related Persona Department: {persona.get('role', '-')}\n\n"
        "## Symptoms\n"
        f"- {issue_summary}\n\n"
        "## Root Cause\n"
        f"- {root_cause}\n\n"
        "## Troubleshooting Checklist\n"
        f"{checks_block}\n\n"
        "## Resolution Steps\n"
        f"{steps_block}\n\n"
        "## Analyst Notes (From Ticket)\n"
        f"{recent_agent_notes}\n\n"
        "## Validation\n"
        "- Confirm user can complete the original action without error.\n"
        "- Confirm no policy/security exceptions were introduced.\n"
        "- Capture timestamp and impacted user details in final documentation.\n"
    )
