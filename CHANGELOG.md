# Changelog

All notable changes to HD Simulation Software are documented in this file.

The format is inspired by Keep a Changelog and uses semantic versioning.

## [Unreleased]

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
