# V2 Release Runbook

Use this runbook for every `v2.x` milestone release.

## 1) Prepare the release branch

1. Start from your v2 branch (for example `v2-llm-dev`).
2. Confirm your working tree is clean:

```bash
git status
```

## 2) Update version and docs

Update all required release artifacts before tagging:

1. `simulator/pyproject.toml`
2. `simulator/src/helpdesk_sim/__init__.py`
3. `simulator/src/helpdesk_sim/main.py`
4. `CHANGELOG.md`
5. `README.md`
6. `simulator/README.md`

Release policy:

- Patch (`v2.x.y`): bug fixes or small improvements
- Minor (`v2.y.0`): additive feature release
- Major (`v3.0.0`): breaking changes

## 3) Run release checks

From `simulator/`:

```bash
make release-check
make test
```

`make release-check` validates version sync across:

- `pyproject.toml`
- `__init__.py`
- `main.py`
- latest changelog heading

## 4) Build draft release notes

From `simulator/`:

```bash
make release-notes
```

This generates `simulator/release-notes-draft.md` from the latest `CHANGELOG.md` section.

## 5) Commit and tag

From repo root:

```bash
git add .
git commit -m "release: v2.0.3"
git tag v2.0.3
git push origin v2-llm-dev
git push origin v2.0.3
```

## 6) Publish GitHub release

1. Create a new GitHub Release for the tag (for example `v2.0.3`).
2. Use `.github/release-template.md` as the release body format.
3. Paste the generated draft notes and fill upgrade/testing notes.

## 7) Post-release validation

1. Pull the release tag on homelab deployment target.
2. Start simulator and verify:
   - `GET /health` shows expected version
   - `/ui` loads
   - `/god` behavior matches current config
   - LLM status/wake path behaves as expected
3. Log any rollback steps if needed.
