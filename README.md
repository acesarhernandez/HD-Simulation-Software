# HD Simulation Software

Operations toolkit for building and running a realistic help desk training environment with Zammad.

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
