# Zammad Read-Only Audit Checklist (BMM Lab)

Purpose: confirm your current live Zammad configuration before making changes.

This checklist is intentionally read-only. You will gather evidence first, then we decide what to change.

## 1) Prerequisites

- You can sign in as a Zammad admin user.
- You have an API token for that admin user.
- You can reach your homelab Zammad URL from this machine.
- Zammad does not need to be installed on this machine; only network reachability is required.

How to create an API token in Zammad:
1. Log in as admin.
2. Open avatar/profile menu.
3. Go to `Profile` > `Token Access`.
4. Create a token with a clear name like `readonly-audit`.
5. Copy the token once and store it safely.

## 2) Run the read-only export script

From project root (`/Users/cesarhernandez/Projects/HelpDesk Software`):

```bash
chmod +x ./scripts/zammad_readonly_audit.sh
./scripts/zammad_readonly_audit.sh \
  --url "https://YOUR-ZAMMAD-URL" \
  --token "YOUR_API_TOKEN"
```

Quick connectivity check before running script:

```bash
curl -k -I "https://YOUR-ZAMMAD-URL"
```

Expected result:
- A folder like `audit-output/zammad-audit-YYYYMMDD-HHMMSS/`
- A `summary.md` file with quick findings
- Raw JSON snapshots in `raw/`

## 3) BMM target-state checks

Mark each item as `PASS`, `PARTIAL`, or `MISSING` after reviewing `summary.md` and Zammad UI.

### A. Ticket model and classification

- [ ] Priorities exist: `1 low`, `2 normal`, `3 high`.
- [ ] Custom ticket field `support_level` exists.
- [ ] `support_level` options include `Tier 1` and `Tier 2`.
- [ ] New tickets default to `support_level = Tier 1`.
- [ ] Customers cannot see internal workflow fields.

### B. SLA and escalation

- [ ] SLA exists for each priority (`high`, `normal`, `low`).
- [ ] First response targets match your model.
- [ ] SLA calendars use business hours (PST Mon-Fri 09:00-17:00 + holidays).
- [ ] Time-event trigger exists for first-response breach.
- [ ] On breach: tag `sla_breached` is added.
- [ ] On breach: `support_level` is set to `Tier 2`.

### C. Customer permissions and edit restrictions

- [ ] Customer can create ticket.
- [ ] Customer can reply and add attachments.
- [ ] Customer cannot change ticket `group`.
- [ ] Customer cannot change ticket `state`.
- [ ] Customer cannot change ticket `priority`.
- [ ] Customer cannot edit internal-only fields.

### D. Agent operating views

- [ ] Overview `New - Needs Triage` exists.
- [ ] Overview `Breached SLA` exists.
- [ ] Overview `Tier 2 Queue` exists.
- [ ] Sort and filters support daily triage workflow.

### E. Documentation discipline

- [ ] Ticket template exists for: Problem, Impact, Troubleshooting, Root Cause, Resolution, Prevention.
- [ ] Escalation notes from Tier 1 to Tier 2 are documented in-ticket.
- [ ] Closure confirmation pattern exists.

## 4) Evidence package for change planning

Keep these files for audit history:

- `summary.md`
- `raw/slas.json`
- `raw/triggers.json`
- `raw/core_workflows.json`
- `raw/object_manager_attributes.json`
- `raw/overviews.json`

These are the minimum files we will diff before and after each configuration change.

## 5) Next step after audit

After you run the script, share:
- Your `summary.md` contents
- Any item you marked `MISSING` or `PARTIAL`

Then I will produce a zero-guess, click-by-click implementation sequence for the missing items only.
