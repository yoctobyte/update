# Project Meta
**Purpose:** shared deep handover, constraints, and agent-coordination file
**Last updated:** 2026-03-31
**Branch context:** `dev`
**Live serving assumption:** production runs from `main`; do not disturb the running instance from `dev`

## Audience

This file is primarily for agents and deep project handover.

Principle:
- do not hide project truth from humans
- but do separate audiences

Human-oriented operational instructions should stay easy to find in:
- [NOTES.md](/home/user/lokaalnieuws/NOTES.md)

Structured cross-agent state should live in:
- [PROJECT_STATE.yaml](/home/user/lokaalnieuws/docs/PROJECT_STATE.yaml)

Agent-oriented continuity can assume more context and live here:
- git state
- handover notes
- dirty worktree awareness
- current branch/runtime constraints
- cross-session project direction

## How To Use This File

Any agent may edit this file.

When updating:
- update [PROJECT_STATE.yaml](/home/user/lokaalnieuws/docs/PROJECT_STATE.yaml) first when progress/goals/bugs/todos change
- keep timestamps explicit: `YYYY-MM-DD HH:MM TZ`
- update `Todo`, `Done`, and `Handover`
- record whether work was committed or still dirty
- record any constraints that the next agent must preserve
- prefer short factual bullets over long prose

Recommended agent read order:
1. [AGENTS.md](/home/user/lokaalnieuws/AGENTS.md)
2. [PROJECT_STATE.yaml](/home/user/lokaalnieuws/docs/PROJECT_STATE.yaml)
3. [PROJECT_META.md](/home/user/lokaalnieuws/docs/PROJECT_META.md)
4. [NOTES.md](/home/user/lokaalnieuws/NOTES.md)

## Working Constraints

Timestamp: 2026-03-30 00:00 Europe/Amsterdam

- The repo may be actively running for crawlers and public traffic.
- Do not use `run.sh` casually from `dev`.
- Prefer read-only inspection unless the task explicitly needs code changes.
- Be conservative around anything that could touch the running instance.
- Stable URLs matter for public navigation.
- Avoid shaping primary navigation around query parameters like `/?topic=...`.
- Public product direction is currently experiment-first:
  - themed views first
  - decide later what the real homepage/front page should be

## Git State Rules

Timestamp: 2026-03-30 00:00 Europe/Amsterdam

- `main` = live/stable
- `dev` = integration branch
- feature work should assume `dev` may be ahead of live production
- do not restart production from `dev`
- when making commits, stage only relevant files
- do not sweep unrelated untracked files into a commit

Unrelated/untracked items may exist locally.
Treat them as intentional unless told otherwise.

## Current Product Direction

Timestamp: 2026-03-30 00:00 Europe/Amsterdam

- Current "frontpage" is moving conceptually toward `Uitgelicht`
- Upcoming lane concepts:
  - `Uitgelicht`
  - `Vandaag`
  - `Week`
- These are themed views first, not final homepage commitments
- Admin should be able to choose which main view currently maps to `/`
- The lane URLs themselves should remain stable while experiments continue

See:
- [security_review_2026-03-30.md](/home/user/lokaalnieuws/docs/security_review_2026-03-30.md)
- [security_audit_2026-03-31.md](/home/user/lokaalnieuws/docs/security_audit_2026-03-31.md)
- [todo_next_frontpage_today_weekly_2026-03-30.md](/home/user/lokaalnieuws/docs/todo_next_frontpage_today_weekly_2026-03-30.md)

## Todo

Timestamp: 2026-03-30 00:00 Europe/Amsterdam

- Turn the `Uitgelicht` / `Vandaag` / `Week` concept note into implementable schema and route changes when ready.
- Keep homepage routing stable while allowing admin to choose the active main view.
- Build lane ranking in an experiment-friendly way:
  - pairwise comparisons
  - allow `higher`, `lower`, `similar`
  - optional soft preference inside `similar`
  - possible merge-hint metadata
- Preserve the current no-cookie public design unless there is a strong reason to change it.
- Revisit admin-only SSRF and trusted-markdown issues later, separately from public-surface work.
- Fold the 2026-03-31 broader security audit into a concrete remediation order when security work resumes.

## Done

Timestamp: 2026-03-30 00:00 Europe/Amsterdam

- Story/verhaal cards were integrated into overview pages and detail flows.
- Frontpage persistence now collapses to one representative article per public story so visible output matches stored selection better.
- Public bearer-token opinion edit route was rate-limited:
  - `10 per minute; 30 per hour`
- Public-facing security review was documented.
- Themed-view concept/design note was documented and refined.
- A broader read-only security audit was documented in `docs/security_audit_2026-03-31.md`, confirming no obvious unauthenticated server-compromise path while recording trust-boundary issues around markdown, SSRF, SVG uploads, cookie config, and bearer-link lifetime.

Recent commit:
- `3835dcb` — `Add story cards to overviews and harden public edit flow`
- `15efc4c` — `Add human and agent project handover docs`

## Handover

Timestamp: 2026-03-30 00:00 Europe/Amsterdam

If another agent picks this up next:

- Read [AGENTS.md](/home/user/lokaalnieuws/AGENTS.md) first.
- Then read [PROJECT_STATE.yaml](/home/user/lokaalnieuws/docs/PROJECT_STATE.yaml).
- Then read:
  - [NOTES.md](/home/user/lokaalnieuws/NOTES.md)
  - [security_review_2026-03-30.md](/home/user/lokaalnieuws/docs/security_review_2026-03-30.md)
  - [security_audit_2026-03-31.md](/home/user/lokaalnieuws/docs/security_audit_2026-03-31.md)
  - [todo_next_frontpage_today_weekly_2026-03-30.md](/home/user/lokaalnieuws/docs/todo_next_frontpage_today_weekly_2026-03-30.md)
- Assume `dev` is not the live branch.
- Assume the running site should not be disturbed.
- Prefer small scoped commits.
- Keep documentation current as you go; do not leave reasoning only in chat history.

Current known dirty state after the last recorded commit:
- untracked: `.wageningen-test.pid`
- untracked local content/tooling areas also present:
  - `dossiers/`
  - `histsearch/`
  - `poo/`

Interpretation:
- do not assume these are accidental
- do not sweep them into unrelated commits

## Open Questions

Timestamp: 2026-03-30 00:00 Europe/Amsterdam

- Should `Uitgelicht` remain article-backed internally for a while, or should all lanes move to a unified lane-item model?
- Should the first experiment after `Uitgelicht` be only `Vandaag`, or should the schema anticipate `Week` immediately?
- How much of the pairwise ranking should be heuristic first, versus LLM-assisted later?
- When the admin chooses the active homepage lane, should the nav visually mark that choice or keep lane labels fixed and neutral?

## Update Template

Copy this block when making the next substantial change:

```md
## Update

Timestamp: YYYY-MM-DD HH:MM TZ

### Done
- ...

### Todo
- ...

### Handover
- ...

### Git
- branch:
- commit:
- dirty files left:
```

## Update

Timestamp: 2026-04-02 20:16 Europe/Amsterdam

### Done
- Audited repeated ORM/SQL query patterns against current index coverage.
- Added Alembic migration `0023_query_indexes.py` for missing composite indexes on:
  - article section listings / extraction queue
  - extraction rule lookup
  - news lane ordering
  - story ordering
  - opinion moderation/public ordering

### Todo
- Apply migration `0023` to each town database that should receive the new indexes.
- Re-run query-plan checks after deployment/migration to confirm the temp-sort paths are gone for the targeted queries.

### Handover
- The query/index audit used real `EXPLAIN QUERY PLAN` checks against `data/wageningen/database.db`.
- The largest observed non-article table was `news_lane_items`, so lane ordering indexes were prioritized.

### Git
- branch: `dev`
- commit:
- dirty files left:
  - `.wageningen-test.pid`
  - `docs/security_audit_2026-03-31.md`
  - `histsearch/`
  - `poo/`

## Update

Timestamp: 2026-03-31 21:00 Europe/Amsterdam

### Done
- Performed a broader read-only security audit of the application code.
- Recorded the audit in `docs/security_audit_2026-03-31.md`.
- Confirmed the earlier public-surface review still broadly holds: no obvious public auth bypass, arbitrary file read, or RCE path was found from static inspection.
- Expanded the tracked follow-up set to include:
  - trusted-markdown stored-XSS risk
  - incomplete admin-side SSRF hardening
  - editorial SVG upload risk
  - deployment-sensitive admin cookie security
  - non-expiring pending opinion edit links

### Todo
- Convert the 2026-03-31 audit findings into a remediation sequence when security work is prioritized.
- Keep the earlier public-surface review and the broader audit note aligned if mitigations land.

### Handover
- If security work resumes, read both `docs/security_review_2026-03-30.md` and `docs/security_audit_2026-03-31.md`.
- Treat the markdown, SSRF, and SVG issues as trust-boundary problems rather than generic anonymous-public exploits.

### Git
- branch: `dev`
- commit: `5cc2302`
- dirty files left:
  - `.wageningen-test.pid`
  - `dossiers/`
  - `histsearch/`
  - `poo/`

Timestamp: 2026-03-30 00:45 Europe/Amsterdam

### Done
- Tested onboarding from scratch using `PROJECT_META.md`, `NOTES.md`, the security note, and the themed-view concept note.
- Confirmed that a new agent can recover the main branch/runtime constraints and current product direction from docs alone.
- Tightened handover quality by recording the currently known dirty/untracked state here.
- Added explicit human-vs-agent documentation split and committed it as `15efc4c`.
- Added a structured cross-agent state file plus `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` compatibility entrypoints.
- Committed the multi-agent documentation checkpoint as `75b941c`.
- Completed the first implementation slice for stable lane routing in `5cc2302`:
  - added a public `Uitgelicht` route
  - made `/` configurable between `Uitgelicht` and lokaal nieuws
  - aligned admin controls and nav labels with the new route shape

### Todo
- Keep this file current after each substantial coding session or commit.
- When the themed-view work advances, move the most current implementation decision back into this file, not only into the concept note.
- Keep `PROJECT_STATE.yaml` as the canonical source for progress/goals/bugs/todos.
- Next implementation target: schema and ranking groundwork for `Vandaag` / `Week`.

### Handover
- If you start fresh, read `AGENTS.md`, then `PROJECT_STATE.yaml`, then this file, then `NOTES.md`.
- Before editing, check whether the dirty state listed here still matches `git status`.

### Git
- branch: `dev`
- commit: `5cc2302`
- dirty files left:
  - `.wageningen-test.pid`
  - `dossiers/`
  - `histsearch/`
  - `poo/`
