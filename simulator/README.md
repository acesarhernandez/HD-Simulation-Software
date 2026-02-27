# HD Simulation Software Backend

A config-driven training backend for Zammad labs.

This service generates realistic ticket traffic, listens for analyst responses, simulates customer follow-up behavior, grades closed tickets, and produces daily/weekly performance summaries.

## Release Track

- **V1 (current / stable):** [https://github.com/acesarhernandez/HD-Simulation-Software](https://github.com/acesarhernandez/HD-Simulation-Software) (`main`)
  - Primary target: homelab deployment
  - Default response engine: `rule_based`
- **V2 (in development):**
  - Primary target: same backend with optional remote LLM endpoint
  - Planned response engine mode: `ollama`

## What LLM Changes In V2

V1 already covers queue generation, ticket injection, poller loops, hints, scoring, and reports without any LLM.  
V2 keeps that foundation and adds optional LLM behavior where it improves realism:

- **Natural customer dialog:** less canned follow-up phrasing, better continuity across replies.
- **Adaptive hints/coaching:** hint text can adapt to your actual troubleshooting steps.
- **Richer closure feedback:** explanation quality can improve while deterministic score math stays intact.
- **Scenario expression variety:** same underlying truth, but more variation in ticket wording and user tone.

## What v1 Includes

- Session profiles (`normal_day`, `busy_day`, `outage_day`, `tier1_focus`, `tier2_focus`, `sysadmin_focus`, `manual_only`) with clock-in style operation.
- Dynamic ticket volume (`min/max tickets per window`, `window cadence`, `session duration`).
- Tier routing control (`tier1`, `tier2`, `sysadmin`) via weighted distribution.
- Incident injection support (for example, simulated network outage spikes).
- Hidden scenario truth per ticket (root cause, expected checks, valid fixes).
- Poller loop that watches ticket updates and posts simulated customer replies.
- Persona-based customer identities (HR/Finance/etc.) that first reuse existing Zammad department users, then auto-create customer + organization records if needed.
- Hint system with configurable score penalties.
- SLA-aware grading model and performance reports.
- Knowledge article links at scenario level (backend-ready for KB workflows).
- Dashboard includes day-profile definitions and manual ticket generation by filters.
- Dashboard includes mass clock-out, light/dark/auto theme toggle, and readable hint/report summaries with raw JSON.
- Trickle delivery mode enabled by default so tickets arrive gradually instead of all at once.
- Optional v2 response engine integration point for remote Ollama.

## Architecture

The backend is intentionally split into stable modules so you can swap components without rewriting the whole stack.

- `api/`: HTTP endpoints for session control, hints, and reports.
- `services/`: scheduler, poller, generation, grading, and reporting logic.
- `adapters/`: Zammad gateway and dry-run gateway.
- `templates/`: profiles, personas, and scenarios in YAML.
- `repositories/`: SQLite persistence for sessions, tickets, interactions, reports.

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

Dashboard highlights:

- Day profile cards that explain cadence, volume, tier mix, and business-hours behavior.
- Manual ticket generation controls by session, tier, ticket type, department, persona, or scenario.
- Ticket detail panel showing operational metadata, recent interactions, and linked knowledge articles.
- Ticket detail actions for close/delete (single and bulk) plus KB draft generation for closed tickets.
- Ticket delete actions now attempt linked Zammad ticket deletion first, then remove simulator records.
- Hint requests directly in UI with penalty visibility plus plain-English summaries.
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
- `SIM_DB_PATH`: SQLite file path.
- `SIM_POLL_INTERVAL_SECONDS`: how often poller checks for updates.
- `SIM_SCHEDULER_INTERVAL_SECONDS`: how often scheduler checks for due windows.

If your token cannot create/search users, set `SIM_ZAMMAD_CUSTOMER_FALLBACK_EMAIL` to an existing customer user (for example `sim.test@bmm.local`) so ticket creation can still proceed.

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
