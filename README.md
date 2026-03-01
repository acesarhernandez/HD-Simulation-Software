# HD Simulation Software

Operations toolkit for building and running a realistic help desk training environment with Zammad.

## Version Status

- **V1 (current / stable):** [HD Simulation Software v1](https://github.com/acesarhernandez/HD-Simulation-Software) on `main`, designed for homelab deployment with deterministic, rule-based simulation.
- **V2 (in development):** [HD Simulation Software v2 dev branch](https://github.com/acesarhernandez/HD-Simulation-Software/tree/v2-llm-dev), the optional-LLM track that keeps the same backend architecture while adding LLM enhancements.

## V1 vs V2 (LLM)

| Area | V1 (current) | V2 (in development) |
| --- | --- | --- |
| Ticket generation | YAML-driven scenarios, profiles, and weighted scheduling | Same base engine, plus optional LLM variation for more natural ticket phrasing |
| End-user replies | Rule-based follow-up responses from scenario clue maps | Context-aware conversational replies based on ticket history and persona |
| Hinting | Pre-authored hints (`nudge`, `guided_step`, `strong_hint`) | Dynamic hints tailored to your troubleshooting path |
| Grading feedback | Deterministic scoring and plain-English summaries | Same deterministic scoring, plus optional LLM coaching notes, documentation critique, and professionalism review |
| Deployment model | Runs fully on homelab (no LLM required) | Keeps homelab backend and calls remote LLM API (for example Ollama) |

## V2 Design Rules

The `v2` branch keeps the simulator technically grounded by separating deterministic truth from optional AI behavior.

- Ticket creation remains owned by the structured simulator engine.
- Opening ticket wording can be optionally rewritten by the LLM, but the selected scenario and hidden truth stay unchanged.
- Hidden truth, scoring rules, and valid fixes remain deterministic and authored.
- The LLM improves realism, but it does not invent root causes on the fly.
- If the LLM is unavailable, the simulator must continue to function in `v1`-style fallback mode.

Planned `v2` enhancements:

- LLM-assisted conversation after analyst replies.
- Optional LLM rewrite of the opening ticket wording while preserving the same hidden truth.
- Optional LLM coaching notes layered on top of deterministic grading.
- Optional LLM documentation critique after ticket closure.
- Optional professionalism critique that flags hostile or clearly unprofessional analyst language.
- Optional mentor/escalation chat panel that simulates consulting a senior tech.
- Hint wording that can be rephrased by the LLM, while still being sourced from deterministic hidden truth.

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
- New simulator-created tickets land as `new` and unassigned so they stay in the intended Zammad queue.
- Hint mode with penalty controls.
- Daily and weekly performance summaries.
- Built-in dashboard at `http://localhost:8079/ui` with light/dark/auto theme and mass clock-out.
- Shift Control now includes a compact day-profile quick look, while full profile comparisons stay tucked behind an inline expander.
- Ticket detail includes built-in coaching actions, and the dashboard includes a mentor console for internal escalation guidance, communication coaching, SLA guidance, escalation decisions, and documentation tips.
- LLM runtime now includes a small PC online/offline indicator based on whether the configured LLM host is reachable.
- Dashboard actions show visible loading states so you can see when the LLM is generating, the poller is running, or the PC wake request is being sent.
- Plain-language guide at `http://localhost:8079/ui/guide`.
- Extension point for a remote response engine in v2.

Start here:

- [`simulator/README.md`](simulator/README.md)

## Existing Zammad Runbooks

- [Zammad Clean-In-Place Runbook](docs/zammad-clean-in-place-runbook.md)
- [Zammad Read-Only Audit Checklist](docs/zammad-readonly-audit-checklist.md)

## License

MIT
