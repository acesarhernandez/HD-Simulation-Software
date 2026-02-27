from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from helpdesk_sim.domain.models import ClockInRequest, ManualTicketRequest, HintRequest

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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

    runtime.repository.close_ticket(
        ticket_id=ticket_id,
        score={
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
        },
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


@router.get("/v1/reports/daily")
def report_daily(request: Request) -> dict:
    runtime = request.app.state.runtime
    report = runtime.report_service.generate("daily")
    report["english_summary"] = _report_summary(report_type="daily", report=report)
    return report


@router.get("/v1/reports/weekly")
def report_weekly(request: Request) -> dict:
    runtime = request.app.state.runtime
    report = runtime.report_service.generate("weekly")
    report["english_summary"] = _report_summary(report_type="weekly", report=report)
    return report


def _report_summary(report_type: str, report: dict) -> str:
    label = "Daily" if report_type == "daily" else "Weekly"
    closed = int(report.get("tickets_closed", 0))
    avg_score = float(report.get("average_score", 0))
    avg_first_response = float(report.get("average_first_response_minutes", 0))
    avg_resolution = float(report.get("average_resolution_minutes", 0))
    sla_miss = float(report.get("sla_miss_rate", 0)) * 100.0
    summary = (
        f"{label} performance: {closed} tickets closed. "
        f"Average score {avg_score:.2f}, first response {avg_first_response:.2f} minutes, "
        f"resolution {avg_resolution:.2f} minutes, SLA miss rate {sla_miss:.2f}%."
    )
    comparison = report.get("comparison")
    if isinstance(comparison, dict) and "score_delta" in comparison:
        delta = float(comparison["score_delta"])
        direction = "up" if delta >= 0 else "down"
        summary += f" Score trend: {direction} {abs(delta):.2f} vs previous {label.lower()} report."
    return summary


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
