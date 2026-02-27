# Zammad Clean-In-Place Runbook (BMM)

Goal: stabilize your existing Zammad instance so you can start realistic ticket operations immediately, without a full rebuild.

Use this runbook in order. Do not jump around.

## 0) Change window rules (5 minutes)

1. Pick a 60-90 minute block.
2. During this block, no random setting changes outside this checklist.
3. Keep one text file open for notes:
   - date/time
   - setting changed
   - why changed
   - test result

Reason: this gives you repeatable admin discipline (exactly what interviewers look for).

## 1) Baseline snapshot (read-only)

Important:
- Zammad does NOT need to run on your Mac.
- The script runs on your Mac and calls the remote homelab Zammad URL over your LAN.
- Your Mac just needs network reachability to the Zammad web/API endpoint.

From `/Users/cesarhernandez/Projects/HelpDesk Software`:

```bash
chmod +x ./scripts/zammad_readonly_audit.sh
./scripts/zammad_readonly_audit.sh \
  --url "https://YOUR-ZAMMAD-URL" \
  --token "YOUR_API_TOKEN"
```

Then:

```bash
latest="$(ls -1dt ./audit-output/zammad-audit-* | head -n 1)"
cat "$latest/summary.md"
```

Save this path. This is your rollback evidence.

If unsure about reachability, run:

```bash
curl -k -I "https://YOUR-ZAMMAD-URL"
```

If this returns HTTP headers (even 401/302), network path is good.

## 2) Role hygiene first (most important)

If customer users can edit routing fields, roles are usually the first issue.

In Zammad:

1. Go to `Admin > Manage > Roles`.
2. Confirm only one default signup role is active and it is customer-only.
3. Open your customer role and verify it does NOT include agent/admin permissions.
4. Open users (HR, Finance, Marketing, etc.) and verify they only have customer role unless they should work tickets.
5. For your own analyst account, ensure you have agent/admin role.

Target model:
- End users: customer only
- You (solo technician): agent + admin
- Optional future: separate tier1/tier2 agent personas for simulation

## 3) Web channel intake guardrails

Go to `Admin > Channels > Web`.

Set:
1. `Enable ticket creation`: Yes
2. `Group selection for Ticket creation`: only your intake group (for example `Service Desk`)

Reason:
- Customers should not route tickets into internal groups.
- Intake should always start in one controlled queue.

## 4) Ticket object sanity check (Support Level)

Go to `Admin > Objects > Ticket > support_level`.

Set:
1. Field exists as single select.
2. Values:
   - `tier1` -> `Tier 1` (default)
   - `tier2` -> `Tier 2`
3. Customer permission: hidden / not available.
4. Agent permission: shown in create + edit.
5. Optional but recommended: required on agent edit.

Note:
- Existing tickets from before this field may stay blank until touched. That is expected.

## 5) Core Workflow to restrict customer editing

Important concept:
- Core Workflows apply to all roles unless you add role-aware conditions.
- Build customer-specific workflow carefully and test with a customer account.

Go to `Admin > System > Core Workflows > New Workflow`.

Create workflow `CW - Customer Ticket Lockdown`:

1. Object: `Ticket`
2. Context: check both
   - `Creation mask`
   - `Edit mask`
3. Conditions (use a customer-context condition):
   - `Customer` `is` `current user`
4. Actions (customer-visible control fields):
   - `Group` -> `set readonly`
   - `Priority` -> `set readonly`
   - `State` -> `set readonly`
   - `Support Level` -> `remove` (or `hide` if remove unavailable)
   - `Owner` -> `remove`
5. Stop after match: `yes`
6. Priority: `200` (execute early)
7. Save

If `set readonly` does not behave as expected for one field in your version:
- switch that field to `remove`.

## 6) SLA breach trigger (tag + tier promotion)

Go to `Admin > Manage > Triggers` and edit `Tag SLA Breach`.

Set:
1. Activated by: `time event`
2. Condition:
   - `Escalation at` `first response time` `within last` `1 minute`
   - Optional safety: `State is not closed` and `State is not pending close`
3. Actions:
   - `add tag` -> `sla_breached`
   - `support_level` -> `tier2`
4. Active: yes

Reason:
- Breach becomes measurable (`tag`) and operational (`tier2` queue).

## 7) Build your 3 operating overviews

Go to `Admin > Manage > Overviews`.

Create these overviews (available for agent/admin roles):

1. `New - Needs Triage`
   - Conditions:
     - `State is new`
     - `Support Level is tier1`
   - Sort: `Created at` ascending

2. `Breached SLA`
   - Conditions:
     - `Tags contains one sla_breached`
     - `State is not closed`
   - Sort: `Escalation at` ascending (or `Updated at` descending)

3. `Tier 2 Queue`
   - Conditions:
     - `Support Level is tier2`
     - `State is not closed`
   - Sort: `Updated at` descending

Tip:
- Keep overview count low (avoid performance noise).

## 8) Functional test plan (must pass before freeze)

Run these tests with a customer account and an agent account.

Test A: customer create ticket
1. Login as customer.
2. Create ticket.
3. Verify defaults:
   - Priority = Normal
   - Support Level hidden to customer
   - Group not freely changeable

Test B: customer edit restrictions
1. Open existing ticket as customer.
2. Verify cannot change group/state/priority.
3. Verify can still add reply + attachment.

Test C: SLA first response behavior
1. Create new high-priority test ticket.
2. Add internal note as agent.
3. Verify SLA first-response timer continues.
4. Add customer-visible reply (or phone call article).
5. Verify first-response escalation stops.

Test D: breach automation
1. Create high-priority test ticket and do not respond.
2. Wait until first-response breach.
3. Verify:
   - tag `sla_breached` added
   - support_level changed to `tier2`
   - ticket appears in `Breached SLA` and `Tier 2 Queue`

## 9) Freeze and operate

After tests pass:
1. Do not add new workflows for 14 days.
2. Work real simulated tickets daily.
3. Use only these actions during run period:
   - triage
   - troubleshooting notes
   - escalation notes
   - resolution documentation

That creates resume-ready operational evidence.

## 10) Resume bullets you can claim after this runbook

- Configured and stabilized a self-hosted Zammad service desk for a 20-user hybrid business simulation.
- Implemented priority-based SLA controls with breach automation and escalation tagging.
- Enforced customer field restrictions via Core Workflows to protect routing and ticket state integrity.
- Built triage, SLA breach, and Tier 2 operational queues to support structured incident handling.

## References (official docs)

- Core Workflows (behavior and role warning): https://admin-docs.zammad.org/en/6.4/system/core-workflows/how-do-they-work.html
- Core Workflow limitations: https://admin-docs.zammad.org/en/6.4/system/core-workflows/limitations.html
- Object attribute permissions: https://admin-docs.zammad.org/en/6.2/system/objects/permissions.html
- Triggers (action/time event model): https://admin-docs.zammad.org/en/latest/manage/trigger/how-do-they-work.html
- Overviews: https://admin-docs.zammad.org/en/6.4/manage/overviews.html
- Web channel customer creation controls: https://admin-docs.zammad.org/en/pre-release/channels/web.html
- SLAs and first response behavior: https://admin-docs.zammad.org/en/6.3/manage/slas/how-do-they-work.html
