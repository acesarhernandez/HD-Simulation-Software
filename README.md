# HD Simulation Software

Operations toolkit for building and running a realistic help desk training environment with Zammad.

## Version Status

- **V1 (current / stable):** [HD Simulation Software v1](https://github.com/acesarhernandez/HD-Simulation-Software) on `main`, designed for homelab deployment with deterministic, rule-based simulation.
- **V2 (in development):** LLM-enhanced simulation track being developed for richer user behavior and coaching while keeping the same backend architecture.

## V1 vs V2 (LLM)

| Area | V1 (current) | V2 (in development) |
| --- | --- | --- |
| Ticket generation | YAML-driven scenarios, profiles, and weighted scheduling | Same base engine, plus optional LLM variation for more natural ticket phrasing |
| End-user replies | Rule-based follow-up responses from scenario clue maps | Context-aware conversational replies based on ticket history and persona |
| Hinting | Pre-authored hints (`nudge`, `guided_step`, `strong_hint`) | Dynamic hints tailored to your troubleshooting path |
| Grading feedback | Deterministic scoring and plain-English summaries | Same deterministic scoring, plus optional LLM coaching notes |
| Deployment model | Runs fully on homelab (no LLM required) | Keeps homelab backend and calls remote LLM API (for example Ollama) |

## Repository Contents

- [`docs/`](docs): operational runbooks, audit checklists, and templates.
- [`scripts/`](scripts): support scripts for read-only Zammad audits.
- [`simulator/`](simulator): config-driven ticket simulation backend (v1) with grading, hints, and reporting.

## Simulator

The simulator is designed for self-hosted Zammad labs where you want controlled ticket generation and measurable practice outcomes.

Key capabilities:

- Dynamic ticket volumes by time window.
- Default trickle delivery so generated windows arrive gradually.
- Tier-targeted ticket streams (`tier1`, `tier2`, `sysadmin`).
- Hidden scenario truth and deterministic grading.
- Hint mode with penalty controls.
- Daily and weekly performance summaries.
- Built-in dashboard at `http://localhost:8079/ui` with light/dark/auto theme and mass clock-out.
- Plain-language guide at `http://localhost:8079/ui/guide`.
- Extension point for a remote response engine in v2.

Start here:

- [`simulator/README.md`](simulator/README.md)

## Existing Zammad Runbooks

- [Zammad Clean-In-Place Runbook](docs/zammad-clean-in-place-runbook.md)
- [Zammad Read-Only Audit Checklist](docs/zammad-readonly-audit-checklist.md)

## License

MIT
