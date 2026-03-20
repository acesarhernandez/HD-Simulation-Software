# HD Simulation Software Backend

A config-driven training backend for Zammad labs.

This service generates realistic ticket traffic, listens for analyst responses, simulates customer follow-up behavior, grades closed tickets, and produces daily/weekly performance summaries.

## Release Track

- **V1 (current / stable):** [https://github.com/acesarhernandez/HD-Simulation-Software](https://github.com/acesarhernandez/HD-Simulation-Software) (`main`)
  - Primary target: homelab deployment
  - Default response engine: `rule_based`
- **V2 (in development):** [https://github.com/acesarhernandez/HD-Simulation-Software/tree/v2-llm-dev](https://github.com/acesarhernandez/HD-Simulation-Software/tree/v2-llm-dev)
  - Primary target: same backend with optional remote LLM endpoint
  - Response engine mode: optional `ollama` with deterministic fallback
  - If the LLM is unavailable, the simulator can fall back to rule-based replies
  - Version line follows milestone tags (`v2.x.y`)

## What LLM Changes In V2

V1 already covers queue generation, ticket injection, poller loops, hints, scoring, and reports without any LLM.  
V2 keeps that foundation and adds optional LLM behavior where it improves realism:

- **Natural customer dialog:** less canned follow-up phrasing, better continuity across replies.
- **Opening ticket variation:** the initial ticket body can be rewritten by the LLM while the same scenario and hidden truth remain in force.
- **Conversation continuity:** recent ticket interactions can be included in the LLM prompt for better follow-up consistency.
- **Adaptive hints/coaching:** hint text can adapt to your actual troubleshooting steps.
- **Richer closure feedback:** explanation quality can improve while deterministic score math stays intact.
- **Professionalism review:** analyst tone can be checked and called out in post-close coaching.
- **Mentor operations guidance:** the mentor path can coach on communication, SLA, escalation, documentation, and help desk best practices, not just technical fixes.
- **Scenario expression variety:** same underlying truth, but more variation in ticket wording and user tone.
- **Shared engine control mode:** when configured, wake/status calls are proxied through a homelab engine-control service while direct Ollama inference stays local to the simulator.
- **Manual KB proposal workflow:** propose an article from a closed ticket, review and revise the draft, then publish it to an external KB provider.
- **Hidden God Mode training:** optional guided route (`/god`) with phase-by-phase walkthrough coaching, attempt-vs-ideal comparison, draft helpers, and separate guided-training reports.

## V2 Design Rules

The `v2` branch uses the LLM as an enhancement layer, not as the source of truth.

- Ticket creation remains driven by the existing structured scenario engine.
- Hidden truth remains authored, deterministic, and technically accurate.
- The LLM does not invent arbitrary root causes, fixes, or grading rules.
- Deterministic grading remains the authoritative score.
- If the LLM is offline or returns weak output, the simulator falls back safely to `v1`-style behavior.

This keeps the simulator realistic without letting AI drift break scoring, troubleshooting validity, or scenario integrity.

## Planned V2 Enhancements

- Optional LLM rewrite of opening ticket language for more natural variation without changing the underlying scenario.
- Expanded structured scenario dimensions (device, location, urgency, business context, user tone) so ticket streams feel less repetitive before any freeform AI variation is applied.
- Optional LLM coaching notes attached to deterministic grading results.
- Optional LLM documentation critique so post-close feedback can assess note quality and communication.
- Optional professionalism critique so post-close feedback can flag hostile or clearly inappropriate analyst replies.
- Optional mentor/escalation chat panel in the UI to simulate consulting a senior tech or sysadmin.
- Optional mentor guidance that can answer ticket-operation questions about wording, SLA handling, escalation decisions, triage, and documentation while staying grounded in the selected ticket.
- Hint responses that stay grounded in the structured hint bank, but can be reworded by the LLM into more natural coaching language.
- Manual KB proposal and review queue with ticket traceability, revision history, and provider-backed publish flow.
- Hidden God Mode walkthrough enhancements for beginner-safe ticket handling phases and replay-driven training.

## What v1 Includes

- Session profiles (`normal_day`, `busy_day`, `outage_day`, `tier1_focus`, `tier2_focus`, `sysadmin_focus`, `manual_only`) with clock-in style operation.
- Dynamic ticket volume (`min/max tickets per window`, `window cadence`, `session duration`).
- Tier routing control (`tier1`, `tier2`, `sysadmin`) via weighted distribution.
- Incident injection support (for example, simulated network outage spikes).
- Hidden scenario truth per ticket (root cause, expected checks, valid fixes).
- Poller loop that watches ticket updates and posts simulated customer replies.
- Poller ignores internal Zammad notes so simulated customers only answer public agent replies.
- Persona-based customer identities (HR/Finance/etc.) that first reuse existing Zammad department users, then auto-create customer + organization records if needed.
- Hint system with configurable score penalties.
- SLA-aware grading model and performance reports.
- Knowledge article links at scenario level plus a manual KB proposal system for closed tickets.
- New simulator-created tickets are sent to Zammad as `new` and unassigned.
- Dashboard includes a compact day-profile quick look inside Shift Control plus manual ticket generation by filters.
- Dashboard includes mass clock-out, light/dark/auto theme toggle, and readable hint/report summaries with raw JSON.
- Trickle delivery mode enabled by default so tickets arrive gradually instead of all at once.
- Optional v2 response engine integration point for remote Ollama.
- Optional opening-message rewrite in `v2` so initial ticket bodies can vary without changing scenario truth.
- Optional `KB Review` panel in the dashboard for draft inspection, revision, approval, and publish actions.
- Optional hidden `/god` guided training route with separate scoring/reports.

## God Mode (Hidden Guided Training)

God Mode is an opt-in training assist for beginner analysts.

- Access route: `/god`
- No link is shown in `/ui` or `/ui/guide`
- Optional key gate: return `404` unless correct key is provided
- Training flow: intake -> identity/security -> impact -> communication -> troubleshooting -> least privilege -> resolve/escalate -> documentation -> closure -> replay
- Draft helpers: public reply, internal note, escalation handoff
- Separate reporting mode (`guided_training`) when enabled

## Architecture

The backend is intentionally split into stable modules so you can swap components without rewriting the whole stack.

- `api/`: HTTP endpoints for session control, hints, reports, and KB review workflow.
- `services/`: scheduler, poller, generation, grading, and reporting logic.
- `adapters/`: Zammad gateway, dry-run gateway, and external KB provider adapters.
- `templates/`: profiles, personas, and scenarios in YAML.
- `repositories/`: SQLite persistence for sessions, tickets, interactions, reports, and KB draft/review state.

Core runtime flow:

1. Clock in to a profile.
2. Scheduler creates tickets at each configured window.
3. Poller checks for new agent replies.
4. Simulator posts customer follow-up responses.
5. Ticket close triggers grading.
6. Daily/weekly summary reports are generated on demand.

## Project Layout

```text
simulator/
  src/helpdesk_sim/
    api/
    adapters/
    domain/
    repositories/
    services/
    templates/
  tests/
  Dockerfile
  docker-compose.example.yml
  pyproject.toml
```

## Requirements

- Python 3.11+
- Network reachability from this service to Zammad
- API token for a Zammad admin/service account

## Quick Start (Local)

From the `simulator` directory:

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn helpdesk_sim.main:app --host 0.0.0.0 --port 8079
```

Open API docs:

- [http://localhost:8079/docs](http://localhost:8079/docs)
- [http://localhost:8079/ui](http://localhost:8079/ui) (Dashboard)
- [http://localhost:8079/ui/guide](http://localhost:8079/ui/guide) (Plain-language guide)
- [http://localhost:8079/god](http://localhost:8079/god) (Hidden guided training route; requires enable flag and optional key)
- [http://localhost:8079/v1/runtime/response-engine](http://localhost:8079/v1/runtime/response-engine) (Response engine status)
- `POST /v1/runtime/wake-llm-host` (Manual wake trigger; proxies to engine-controller when configured, otherwise uses legacy local WoL fallback)
- `POST /v1/tickets/<ticket_id>/coach` (Post-close coaching note grounded in deterministic grading data)
- `POST /v1/tickets/<ticket_id>/mentor` (Internal mentor / escalation guidance for the selected ticket)
- `POST /v1/tickets/<ticket_id>/kb/propose` (Manual KB proposal from a closed ticket)
- `GET /v1/kb/review-items` (Review queue)
- `POST /v1/kb/review-items/<review_item_id>/revise` (Revise a KB draft)
- `POST /v1/kb/review-items/<review_item_id>/approve` (Approve a draft for publish)
- `POST /v1/kb/review-items/<review_item_id>/publish` (Publish to the configured KB provider)
- `GET /v1/god/config` (God mode config/status)
- `POST /v1/god/tickets/<ticket_id>/start` (Start guided walkthrough)
- `GET /v1/god/tickets/<ticket_id>/walkthrough` (Phase and gate status)
- `POST /v1/god/tickets/<ticket_id>/phase/<phase_key>/attempt` (Submit trainee attempt)
- `POST /v1/god/tickets/<ticket_id>/phase/<phase_key>/advance` (Advance phase if gate passed)
- `POST /v1/god/tickets/<ticket_id>/draft/public-reply` (Generate guided public draft)
- `POST /v1/god/tickets/<ticket_id>/draft/internal-note` (Generate guided internal note)
- `POST /v1/god/tickets/<ticket_id>/draft/escalation-handoff` (Generate escalation handoff draft)
- `GET /v1/god/tickets/<ticket_id>/replay` (Attempt-vs-ideal replay)
- `GET /v1/god/reports/daily` / `GET /v1/god/reports/weekly` (Guided-only reports)

Dashboard highlights:

- Shift Control includes a compact day-profile quick look, with the full profile comparison hidden behind an inline expander.
- Active sessions are surfaced beside manual generation so live shift selection stays close to ticket creation.
- Manual ticket generation controls by session, tier, ticket type, department, persona, or scenario.
- Ticket detail panel showing operational metadata, recent interactions, and linked knowledge articles.
- Ticket detail actions for close/delete (single and bulk) plus manual KB proposal generation for closed tickets.
- Ticket detail includes a `Coach` action that sends a closed ticket to the coaching endpoint and shows the result in the same panel.
- Ticket delete actions now attempt linked Zammad ticket deletion first, then remove simulator records.
- Hint requests directly in UI with penalty visibility plus plain-English summaries.
- `KB Review` panel shows the draft queue, source-ticket lineage, revision prompt, approval notes, and publish controls.
- LLM runtime status can merge engine-controller state (`offline`, `waking`, `pc_online`, `ready`) when controller mode is configured.
- LLM runtime includes a dedicated engine status badge and keeps existing wake/status routes stable.
- A top-level request badge and per-button busy states show when the UI is actively polling, generating, asking the mentor, or sending a wake request.
- Wake-on-LAN works best when the simulator process sending the packet is on the same LAN as the target PC. A remote Mac instance will usually not be able to send a directed broadcast to your home LAN.
- A dedicated `Mentor Console` lets you ask for higher-tier guidance on a selected ticket without affecting the simulated end-user conversation, including troubleshooting, communication, SLA, escalation, and documentation questions.
- Report cards in plain English plus raw JSON for debugging/auditing.
- Theme selector: `Auto` (follows system), `Light`, or `Dark`.
- `Clock Out All` button to end every active shift in one action.
- Session detail controls to close/delete individual tickets and bulk close/delete for cleanup.

## Quick Start (Homelab Docker)

```bash
cp docker-compose.example.yml docker-compose.yml
# edit docker-compose.yml values

docker compose up -d --build
```

## Easy Configuration Path

If you want the fastest, lowest-friction setup:

1. Copy `.env.example` to `.env`
2. Fill in your Zammad values first
3. Start in `rule_based` mode
4. Only add Ollama/Wake-on-LAN settings after `v1` behavior is stable

Recommended `v1` baseline:

```env
SIM_USE_DRY_RUN=false
SIM_RESPONSE_ENGINE=rule_based
SIM_LLM_HOST_WOL_ENABLED=false
```

Recommended `v2` optional LLM baseline:

```env
SIM_USE_DRY_RUN=false
SIM_RESPONSE_ENGINE=ollama
SIM_OLLAMA_FALLBACK_TO_RULE_BASED=true
```

Recommended `v2` controller mode add-on:

```env
SIM_ENGINE_CONTROL_URL=http://192.168.86.33:8089
SIM_ENGINE_CONTROL_API_KEY=<ENGINE_API_KEY>
SIM_ENGINE_AUTO_WAKE=true
SIM_ENGINE_AUTO_WAKE_TIMEOUT_SECONDS=90
```

Windows LLM host setup guide:

- [../docs/windows-llm-host-setup.md](../docs/windows-llm-host-setup.md)

## Configuration

Environment variables use the `SIM_` prefix.

- `SIM_ZAMMAD_URL`: Zammad base URL.
- `SIM_ZAMMAD_TOKEN`: API token.
- `SIM_ZAMMAD_GROUP_TIER1`: group name for Tier 1 ticket creation.
- `SIM_ZAMMAD_GROUP_TIER2`: group name for Tier 2 ticket creation.
- `SIM_ZAMMAD_GROUP_SYSADMIN`: group name for SysAdmin ticket creation.
- `SIM_ZAMMAD_CUSTOMER_FALLBACK_EMAIL`: optional existing customer email used only if persona customer lookup/create fails.
- `SIM_USE_DRY_RUN`: `true` for local testing without Zammad.
- `SIM_RESPONSE_ENGINE`: `rule_based` (v1 default) or `ollama` (v2 option).
- `SIM_OLLAMA_URL`: remote Ollama endpoint for v2.
- `SIM_OLLAMA_MODEL`: model name for the remote LLM.
- `SIM_OLLAMA_FALLBACK_TO_RULE_BASED`: if `true`, Ollama failures fall back to rule-based replies.
- `SIM_OLLAMA_REWRITE_OPENING_TICKETS`: if `true`, `v2` can rewrite the opening ticket body with the LLM while keeping the same hidden truth.
- `SIM_ENGINE_CONTROL_URL`: optional shared homelab engine-controller base URL (for example `http://192.168.86.33:8089`).
- `SIM_ENGINE_CONTROL_API_KEY`: bearer token for engine-controller auth.
- `SIM_ENGINE_AUTO_WAKE`: if `true`, LLM-backed paths call `ensure-ready` before Ollama generation when controller mode is configured.
- `SIM_ENGINE_AUTO_WAKE_TIMEOUT_SECONDS`: timeout passed to engine-controller `ensure-ready`.
- `SIM_LLM_HOST_LABEL`: UI label for the optional LLM host machine.
- `SIM_LLM_HOST_WOL_ENABLED`: legacy local Wake-on-LAN fallback (used as primary only when controller mode is not configured).
- `SIM_LLM_HOST_MAC`: legacy local fallback MAC address (use physical Ethernet adapter MAC if the PC wakes over wired LAN).
- `SIM_LLM_HOST_WOL_BROADCAST_IP`: legacy local fallback broadcast IP.
- `SIM_LLM_HOST_WOL_PORT`: legacy local fallback UDP port (commonly `7` or `9`).
- `SIM_KB_ENABLED`: turns on the KB proposal/review workflow.
- `SIM_KB_PROVIDER`: current provider name (`zammad` for first implementation).
- `SIM_KB_REVIEW_REQUIRED`: requires approval before publish.
- `SIM_KB_MIN_SCORE`: minimum score used for KB-worthiness recommendations.
- `SIM_KB_SYNC_ON_START`: if `true`, syncs the KB article cache on app startup.
- `SIM_KB_SYNC_INTERVAL_SECONDS`: reserved for future scheduled KB cache refresh logic.
- `SIM_KB_ZAMMAD_KB_ID`: target Zammad knowledge base ID.
- `SIM_KB_ZAMMAD_LOCALE_ID`: target Zammad locale ID.
- `SIM_KB_ZAMMAD_DEFAULT_CATEGORY_ID`: default Zammad KB category for new articles.
- `SIM_KB_ZAMMAD_PUBLISH_MODE`: `internal` or `public`.
- `SIM_GOD_MODE_ENABLED`: enables hidden `/god` route and `/v1/god/*` APIs.
- `SIM_GOD_MODE_ACCESS_KEY`: optional key required for `/god` bootstrap and `/v1/god/*` calls.
- `SIM_GOD_MODE_DEFAULT_ATTEMPT_FIRST`: if `true`, trainee submits an attempt before ideal guidance.
- `SIM_GOD_MODE_REVEAL_MODE`: truth reveal mode (`guided` recommended).
- `SIM_GOD_MODE_SEPARATE_REPORTS`: keep guided reports separate from standard practice reports.
- `SIM_DB_PATH`: SQLite file path.
- `SIM_POLL_INTERVAL_SECONDS`: how often poller checks for updates.
- `SIM_SCHEDULER_INTERVAL_SECONDS`: how often scheduler checks for due windows.

If your token cannot create/search users, set `SIM_ZAMMAD_CUSTOMER_FALLBACK_EMAIL` to an existing customer user (for example `sim.test@bmm.local`) so ticket creation can still proceed.

Wake-on-LAN routing note:

- The simulator can only send a normal Wake-on-LAN broadcast if the machine running the simulator has a route to the target LAN broadcast address.
- If you run `v2` locally on a remote Mac and point Wake-on-LAN at a home LAN broadcast (for example `192.168.86.255`), macOS may return `No route to host`.
- In that remote-use case, the reliable option is controller mode (`SIM_ENGINE_CONTROL_URL`) with wake/readiness handled by your homelab service.

## V2 Release Workflow

Use the v2 release gate before tagging milestones:

- Runbook: [../docs/release-runbook-v2.md](../docs/release-runbook-v2.md)
- Release template: [../.github/release-template.md](../.github/release-template.md)
- Commands (from `simulator/`):
  - `make release-check`
  - `make release-notes`

## Clock-In Workflow

1. List available profiles:

```bash
curl http://localhost:8079/v1/profiles
```

2. Start session (`busy_day` example):

```bash
curl -X POST http://localhost:8079/v1/sessions/clock-in \
  -H "Content-Type: application/json" \
  -d '{"profile_name":"busy_day"}'
```

3. Optional manual tick triggers:

```bash
curl -X POST http://localhost:8079/v1/scheduler/run-once
curl -X POST http://localhost:8079/v1/poller/run-once
```

4. Review session state:

```bash
curl http://localhost:8079/v1/sessions/<session_id>
```

5. Clock out all active sessions:

```bash
curl -X POST http://localhost:8079/v1/sessions/clock-out-all
```

Manual single/batch generation by filters:

```bash
curl -X POST http://localhost:8079/v1/tickets/generate \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<session_id>","count":1,"tier":"tier1","ticket_type":"vpn_issue","department":"Sales"}'
```

## Hint Mode

Hints are controlled per profile and scored with penalties.

Request a hint:

```bash
curl -X POST http://localhost:8079/v1/hints \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"<ticket_id>","level":"nudge"}'
```

Levels:

- `nudge`
- `guided_step`
- `strong_hint`

Penalty values are configured in `templates/profiles.yaml`.

Hint responses include both raw fields and an `english_summary` string.

## Reports

Daily report:

```bash
curl http://localhost:8079/v1/reports/daily
```

Weekly report:

```bash
curl http://localhost:8079/v1/reports/weekly
```

Report payload includes:

- closed ticket count
- average score
- average first response time
- average resolution time
- SLA miss rate
- top missed troubleshooting checks

Report responses include both raw metrics and an `english_summary` string.

Linked knowledge articles for a ticket:

```bash
curl http://localhost:8079/v1/tickets/<ticket_id>/knowledge-articles
```

Create a manual KB proposal from a closed ticket:

```bash
curl -X POST http://localhost:8079/v1/tickets/<ticket_id>/kb/propose
```

List the KB review queue:

```bash
curl http://localhost:8079/v1/kb/review-items
```

Revise a KB proposal:

```bash
curl -X POST http://localhost:8079/v1/kb/review-items/<review_item_id>/revise \
  -H "Content-Type: application/json" \
  -d '{"instruction":"Shorten this article and keep the scope narrow."}'
```

Approve and publish a KB proposal:

```bash
curl -X POST http://localhost:8079/v1/kb/review-items/<review_item_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"notes":"Reviewer approved for internal publication."}'

curl -X POST http://localhost:8079/v1/kb/review-items/<review_item_id>/publish
```

Post-close coaching note for a completed ticket:

```bash
curl -X POST http://localhost:8079/v1/tickets/<ticket_id>/coach
```

Mentor / escalation guidance for an active or closed ticket:

```bash
curl -X POST http://localhost:8079/v1/tickets/<ticket_id>/mentor \
  -H "Content-Type: application/json" \
  -d '{"message":"What would you check next before I escalate this?"}'
```

## Scenario Authoring

Scenarios live in `src/helpdesk_sim/templates/scenarios.yaml`.

Each scenario defines:

- customer-visible problem statement
- hidden root cause
- expected analyst checks
- acceptable resolution keywords
- clue map for customer follow-up responses
- hint bank per hint level
- linked knowledge article IDs

This structure lets you keep deterministic scoring while still generating varied ticket streams.

### Bulk Scenario Pack Workflow

If you want ChatGPT (or any generator) to produce a batch of new scenarios, use a scenario pack:

1. Generate a starter template:

```bash
cd simulator
PYTHONPATH=src python3 scripts/scenario_pack_tools.py template
```

This writes `simulator/scenario-pack-template.yaml`.

2. Paste your generated scenarios into the pack file (`scenarios:` list).

3. Validate before import:

```bash
cd simulator
PYTHONPATH=src python3 scripts/scenario_pack_tools.py validate --pack scenario-pack-template.yaml
```

4. Dry-run the merge:

```bash
cd simulator
PYTHONPATH=src python3 scripts/scenario_pack_tools.py import --pack scenario-pack-template.yaml --dry-run
```

5. Import for real (creates a backup of `scenarios.yaml` by default):

```bash
cd simulator
PYTHONPATH=src python3 scripts/scenario_pack_tools.py import --pack scenario-pack-template.yaml
```

If pack IDs already exist and you intentionally want to replace them:

```bash
cd simulator
PYTHONPATH=src python3 scripts/scenario_pack_tools.py import --pack scenario-pack-template.yaml --allow-overwrite
```

## Extending to v2 (Ollama on Windows)

You can keep this backend on homelab and only point `SIM_OLLAMA_URL` to your Windows Ollama endpoint over Tailscale.

No topology change is required for core simulator services. The only additional dependency is network/API access from homelab to the Ollama host.

## Security Notes

- Use a dedicated service token in Zammad.
- Restrict network access to simulator API endpoints.
- Keep `.env` out of version control.
- Rotate API tokens periodically.

## Development

```bash
make dev
make test
make lint
```

## License

MIT
