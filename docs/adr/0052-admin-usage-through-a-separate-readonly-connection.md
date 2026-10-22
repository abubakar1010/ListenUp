# ADR 0052: Administrator usage reports through a separate read-only connection

- Status: Accepted (owner-approved #100 part 2 plan)
- Date: 2026-10-22
- Sources: #100 and its 2026-10-19 comment; SRS 2.2, NFR-AI-10; ADRs 0041 and 0045

## Decision

The usage endpoint retains ADR 0045's verified-email `CurrentAdmin` gate. A learner
receives the ordinary 404, a signed-out caller 401. The jobs view is unchanged.

`LISTENUP_ADMIN_REPORT_DATABASE_URL` names a separate login granted only
`listenup_readonly`. After authorization, reporting starts a repeatable-read,
read-only transaction and assumes that role locally. It selects only aggregate
fields from `ai.calls` and current day/month counters from `ai.quota_usage`.
The ordinary API connection receives no new membership or grants. Existing #64
grants suffice; no migration is needed. A missing connection, failed read or
invalid quota configuration returns a content-free 503, with no privileged fallback.
The connection pool is created and disposed with the API lifespan.

The report contains today so far and the previous 29 UTC dates, zero-filled by
provider. Count admitted attempts, including pending/failed attempts whose
reservations remain charged, but exclude quota/eligibility refusals. Sum stored
input/output tokens, audio seconds and projected USD cost; cache and reasoning
tokens are already included in input/output totals and must not be added again.
Show the number of calls retaining estimated/reserved usage. Cost is hypothetical,
not a bill or permission to activate paid routing.

Quota counters are read separately so joining monthly/daily/minute buckets never
multiplies calls or costs. Compare current UTC day and calendar-month counters
with current configured free limits; do not invent a rolling 30-day allowance or
historical limits. The admin module reads only allowlisted quota metadata from
the effective `LISTENUP_AI_CONFIG` file (or the packaged default), without importing
the AI layer, constructing adapters, returning options or changing accounting.
Shared provider IDs must have identical day/month limits. Absent dimensions are
uncapped, zero means no allowance, and a provider absent from current configuration
has unknown limits. Removed providers remain visible when accounting has records.

Responses contain no learner identifiers, media, text, raw call records, tasks,
model strings, provider options or exception details. Successful responses are
`private, no-store`. `/admin/usage` uses account-scoped query caching and displays
the ordinary page-not-found on 404. Tables have captions, column/row headers and
keyboard-focusable scroll regions at narrow widths.

## Operations

Provision the report login outside the application using an operator-chosen secret:
grant it `listenup_readonly`, without superuser, BYPASSRLS or API/worker membership.
Put its connection URL securely in `LISTENUP_ADMIN_REPORT_DATABASE_URL` and restart
the API. Do not put production credentials into source control or logs. The role
already exists from the baseline migration; #64 grants SELECT on the accounting
tables. Missing report configuration disables only usage reporting, not jobs or
learner endpoints. Local fake AI configuration has no free caps and is shown as
uncapped; hosted quotas require the operator's verified configuration.

## Consequences

This implements the issue's read-only report role without widening the learner
connection's access to cross-learner analytics. Operators manage one additional
login and connection setting. Configuration represents current limits, not a
historical quota ledger; the page states this limitation explicitly.
