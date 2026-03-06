# Changelog

All notable changes to HD Simulation Software are documented in this file.

The format is inspired by Keep a Changelog and uses semantic versioning.

## [Unreleased]

## [2.0.3] - 2026-03-05

### Added
- Hidden God Mode route at `/god` (no link from standard dashboard/guide) with optional key gate behavior.
- God Mode guided workflow APIs:
  - `GET /v1/god/config`
  - `POST /v1/god/tickets/{ticket_id}/start`
  - `GET /v1/god/tickets/{ticket_id}/walkthrough`
  - `POST /v1/god/tickets/{ticket_id}/phase/{phase_key}/attempt`
  - `POST /v1/god/tickets/{ticket_id}/phase/{phase_key}/advance`
  - `POST /v1/god/tickets/{ticket_id}/reveal-truth`
  - `POST /v1/god/tickets/{ticket_id}/draft/public-reply`
  - `POST /v1/god/tickets/{ticket_id}/draft/internal-note`
  - `POST /v1/god/tickets/{ticket_id}/draft/escalation-handoff`
  - `GET /v1/god/tickets/{ticket_id}/replay`
  - `GET /v1/god/reports/daily`
  - `GET /v1/god/reports/weekly`
- New God Mode training service with phase sequencing, gate checks, attempt comparison, draft generation, and replay output.
- God Mode web UI at `/god` with ticket context selection, phase progression, drafts, replay, and God-only reports.
- New release discipline assets:
  - `docs/release-runbook-v2.md`
  - `.github/release-template.md`
  - `simulator/scripts/release_tools.py`
  - `make release-check`
  - `make release-notes`

### Changed
- Version line moved to `2.0.3` for v2 milestone releases.
- Score payloads now include `meta.score_mode` and `meta.god_mode_used` for guided-training separation.
- Report generation now supports score-mode filtering and stores guided report snapshots under `daily_god` / `weekly_god`.
- Manual close paths are tagged for explicit practice-mode scoring unless ticket hidden truth indicates guided mode.
- God mode access guard returns `404` when disabled or when key validation fails (hidden behavior preserved).
- Added God Mode environment settings in `.env.example`.

### Notes
- This release is for the `v2-llm-dev` branch (development track).
- `main` remains the stable v1 track.

## [0.2.2] - 2026-03-05

### Fixed
- Poller now handles Zammad article sender metadata when `sender` text is missing or numeric and `sender_id` is present.
- Agent replies are correctly detected from `sender_id` mapping (`1=Agent`, `2=Customer`, `3=System`) to avoid missed simulated user responses.

### Changed
- Simulator version bumped from `0.2.1` to `0.2.2`.

## [0.2.1] - 2026-03-05

### Added
- Dashboard header version badge sourced from backend runtime metadata.

### Changed
- `/health` now returns simulator version alongside status.
- Simulator version bumped from `0.2.0` to `0.2.1`.

## [0.2.0] - 2026-03-05

### Added
- V2 engine-controller integration path with shared wake/readiness support (`SIM_ENGINE_CONTROL_*`).
- LLM engine status merge for controller lifecycle states (`offline`, `waking`, `pc_online`, `ready`).
- Optional automatic ensure-ready preflight before LLM-backed operations.
- Knowledge Base proposal workflow foundations (beta/dev): proposal models, services, review queue, and provider scaffolding.
- New backend client for engine-control API integration.
- Additional test coverage for engine-control and KB proposal/review flow services.

### Changed
- Simulator version bumped from `0.1.0` to `0.2.0`.
- Runtime wake route keeps the same API shape but prefers controller mode when configured.
- Runtime response-engine route now surfaces controller-derived engine status details.
- V2 docs and environment examples expanded for controller mode and KB beta workflow.

### Notes
- This release is for the `v2-llm-dev` branch (development track).
- `main` remains the stable v1 track.
