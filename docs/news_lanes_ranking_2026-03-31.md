# News Lanes Ranking — Design & Upgrade Notes
**Date:** 2026-03-31
**Status:** Implemented, heuristic-only

## Overview

The Vandaag and Week lanes use a bounded pairwise ranking system to order news
candidates. The ranking is fully heuristic — no LLM is involved.

## Pipeline

1. **Build candidate pool** — public stories (active + description, latest
   article within window) plus standalone articles (uitgelicht-worthy, not
   already covered by an included story).
2. **Seed sort** — cheap initial ordering by recency, geo scope, source count,
   and story/article type. O(n log n).
3. **Bounded pairwise comparison** — each item is compared against its 6
   nearest seeded neighbors (not all-vs-all). O(n).
4. **Accumulate scores** — wins, losses, similars, soft preference wins/losses.
5. **Rank score** — `max(0, (wins + 0.3*pref_wins - 0.5*losses - 0.15*pref_losses) / 6)`
6. **Freshness score** — exponential decay: `exp(-ln(2) * age_hours / half_life)`
   - Vandaag half-life: 24h
   - Week half-life: 72h
7. **Blend score** — final sort key:
   - Vandaag: 50% rank + 50% freshness
   - Week: 70% rank + 30% freshness
8. **Persist** — top N items stored; editorial overrides (pinned/suppressed/manual)
   survive recomputes.

## Comparator

`_compare(a, b)` scores each candidate independently then looks at the gap:

| Signal | Weight |
|---|---|
| Is story (and other is not) | +1.5 |
| Source count (capped at 5) | × 0.4 |
| Geo scope (local=4, region=3, province=2, national=1) | × 0.3 |
| Uitgelicht-worthy | +0.3 |
| Recency `max(0, 1 - age_hours/72)` | × 0.5 |

Gap thresholds:

| Gap | Outcome |
|---|---|
| ≥ 0.8 | `a_higher` |
| ≤ −0.8 | `b_higher` |
| 0.3 – 0.8 | `similar, prefer A` |
| −0.8 – −0.3 | `similar, prefer B` |
| −0.3 – 0.3 | `similar, no preference` |

A story always beats a single article unless the article is significantly more
local or more recent. The recency term (weight 0.5) is the heaviest single
signal, so a very fresh local article can outscore an older story.

## Lane caps

- Vandaag: max 30 items persisted and displayed
- Week: max 20 items persisted and displayed

## LLM upgrade path

The comparator is the only part that would change. Everything else — the
neighborhood loop, score accumulation, blending, persistence — is
comparator-agnostic.

To add an LLM comparator:

1. Write a new function with the same signature as `_compare(a, b)`:
   ```python
   def _llm_compare(a: LaneCandidate, b: LaneCandidate) -> dict:
       # call LLM, parse response
       return {"result": "a_higher"|"b_higher"|"similar", "preferred": "a"|"b"|None}
   ```
2. Replace the `_compare(a, b)` call inside `_rank()` with `_llm_compare(a, b)`.
3. Add caching (e.g. by candidate-pair hash) to avoid repeated calls for the
   same pair across recomputes.
4. Optionally: use the heuristic comparator first and only call the LLM when
   the heuristic gap falls inside the soft zone (0.3 – 0.8), i.e. for
   genuinely difficult pairs.

The `similar` outcome with a `preferred` field is already supported by the
accumulation logic and admin diagnostics — no schema changes needed.

## Admin diagnostics

`/admin/nieuws-lanes` shows per-item: wins, losses, similars, freshness score,
rank score, and blend score. This is the main tool for inspecting and tuning
the ranking.

## See also

- `app/services/news_lanes.py` — implementation
- `app/models/news_lane.py` — `NewsLaneItem` model
- `docs/todo_next_frontpage_today_weekly_2026-03-30.md` — original design note
