# TODO Next: Uitgelicht, Vandaag, Week
**Date:** 2026-03-30
**Status:** Concept / design note

## Intent

Next step for the product is to move from a single front page toward a clearer
three-lane structure:

- `Uitgelicht`
- `Vandaag`
- `Week`

This note stores the idea, the expected behavior, and the main design choices to
resolve before implementation.

Current product stance:
- main focus is on themed views
- we expect experimentation
- we do not want to lock in the final "front page" concept too early
- admin should be able to decide which main view is currently the homepage
- URLs should remain consistent while that changes

## 1. Rename current frontpage to `Uitgelicht`

### Goal

The current frontpage should be renamed to `Uitgelicht`.

### Behavior

Functional behavior can stay the same as it is today.

This means:
- same inclusion logic
- same article/story collapsing behavior
- same admin workflow

Only the product language changes:
- "frontpage" in the UI becomes `Uitgelicht`
- internally the service/model names may remain unchanged for now if that keeps
  the change small and safe

### Small extension

Admin should get one additional setting:

- choose which main topic acts as the default homepage topic / front topic

This likely means:
- a selected top-level topic/section becomes the default visible lane
- the current homepage logic still runs, but admin can steer the editorial
  center of gravity without hand-curating items

Open question:
- whether this setting chooses a topic filter inside `Uitgelicht`, or whether it
  changes the main landing section label/navigation more broadly

Constraint:
- do not implement this as `/?topic=...`
- homepage identity should come from stable routes and settings, not ad hoc query
  parameters

## 2. Add `Vandaag`

### Goal

Create a `Vandaag` lane/page for recent news.

### Time window

Not strictly 24 hours.

Desired practical window:
- around 36 to 48 hours

Reason:
- avoids an overly thin page on slow news days
- still feels current to the reader

### Candidate pool

Current thought:
- start from items that would already qualify for the current frontpage logic

Possible pool strategies:

1. Only articles/verhalen that make it to `Uitgelicht`
2. All public verhalen, because multi-source coverage is a strong signal
3. A mixed pool:
   - all public verhalen
   - plus standout single articles that pass `Uitgelicht`

Current recommendation:
- use the mixed pool

Reason:
- only `Uitgelicht` may be too narrow
- only verhalen may miss important one-off local items
- the mix preserves breadth while still applying quality signals

### Ranking idea

This lane should not just sort by publication time.

Preferred idea:
- use a soft pairwise ranking system
- think: "which of these two should rank higher?"
- similar to a league table / competition ranking

Meaning:
- compare candidate pairs
- infer a ranking score from repeated pairwise wins/losses
- use that score as the main sort order
- keep recency as a secondary signal

This is not a literal bubble sort implementation requirement.
It is a ranking concept:
- pairwise comparisons
- accumulate score/statistics
- derive a stable but still freshness-aware ordering

Important extension:
- pairwise comparison should support a third outcome: `similar`
- in that case a softer tie-break can still be recorded:
  - `similar, but prefer A`
  - `similar, but prefer B`

This is useful when:
- two items are close in importance
- we do not want to pretend there is a strong gap
- but we still need a stable display order

Additional meaning:
- `similar` can also be treated as a weak merge signal
- especially when two candidates may actually belong to the same broader story
- this does not mean auto-merge by default
- it does mean the ranking system can surface:
  - "these are close in rank"
  - "these may also be candidates for merging"

### Desired output qualities

`Vandaag` should feel:
- current
- important
- not purely chronological
- not too volatile between refreshes

### Stats to store

Store enough ranking metadata to explain and tune the system later.

Possible fields:
- candidate set timestamp
- time window used
- pairwise comparison count
- wins
- losses
- similars
- preferred tie-break wins
- preferred tie-break losses
- rank score
- freshness score
- final blended score
- source type marker (`story` or `article`)

## 3. Add `Week`

### Goal

Create a `Week` lane/page for the strongest recent developments over a longer
window.

### Time window

Not strictly 7 days.

Desired practical window:
- around 10 to 14 days

Reason:
- gives enough material for a meaningful weekly overview
- handles slower local news cycles better

### Candidate pool

Likely the same pool design as `Vandaag`, but with the longer time window.

Current recommendation:
- use the same mixed pool model first
- tune weighting differently from `Vandaag`

### Ranking idea

Same pairwise "soft bubble" approach as `Vandaag`, but with different weights.

For `Week`:
- recency matters less
- significance / breadth matters more
- verhalen should likely get more benefit because they already represent
  multi-source confirmation

### Desired output qualities

`Week` should feel:
- more stable than `Vandaag`
- more synthesis-driven
- less reactive to hourly publication order

## 4. Stories vs articles

### Principle

A `verhaal` should generally count as a stronger signal than a single article,
because it has already crossed a multi-source threshold.

But:
- single articles must still be able to compete
- otherwise important exclusives or highly local items disappear

### Proposed rule of thumb

Use public verhalen as first-class candidates.

Also allow single articles when they:
- pass `Uitgelicht` logic, or
- score unusually high on local relevance / topic strength / freshness

This should result in:
- `Vandaag`: more mixed
- `Week`: more verhalen-heavy

## 5. Ranking model concept

### Initial simple model

Start simpler than a full tournament system.

Candidate approach:

1. Build the pool
2. Generate pairwise comparisons for a bounded subset of pairs
3. Ask a ranking function or LLM:
   - "Which item should rank higher for Vandaag?"
   - "Which item should rank higher for Week?"
   - allowed outcomes:
     - `A higher`
     - `B higher`
     - `similar`
     - optionally: `similar, prefer A`
     - optionally: `similar, prefer B`
4. Convert pairwise outcomes into points / wins / score
5. Blend with freshness
6. Persist the resulting table

This keeps the system:
- explainable
- tunable
- debuggable

### Important constraint

Do not rerank every request live.

Instead:
- calculate periodically in the scheduler
- persist results
- serve cached rankings

That keeps page loads stable and cheap.

## 6. Persistence / model direction

Likely future need:

- a ranking table per lane (`uitgelicht`, `vandaag`, `week`)
- each row points to either an article or a story
- includes computed scores and timestamps

Possible shape:

- `news_lane_items`
  - `lane`
  - `article_id` nullable
  - `story_id` nullable
  - `window_start`
  - `window_end`
  - `rank_score`
  - `freshness_score`
  - `final_score`
  - `wins`
  - `losses`
  - `computed_at`
  - `removed_at`

Important:
- exactly one of `article_id` or `story_id` should be set

## 7. Suggested implementation order

### Phase 1

- rename visible "frontpage" language to `Uitgelicht`
- keep underlying service/model names unchanged where practical
- add admin setting for the main/default topic

### Phase 2

- define candidate-pool builder for `Vandaag`
- include public verhalen + selected single articles
- persist a ranked `Vandaag` list

### Phase 3

- extend same mechanism to `Week`
- tune weights separately

### Phase 4

- add ranking diagnostics in admin
- show why an item is high:
  - story/article
  - freshness
  - pairwise wins
  - final score

## 8. Current recommendation

If implementing next, start with this:

1. Rename current homepage lane to `Uitgelicht`
2. Add admin-selected main topic
3. Build `Vandaag` first, not `Week`
4. Use a mixed candidate pool:
   - public verhalen
   - plus strong single articles
5. Persist rankings in a dedicated table instead of computing them in-view

## 9. Non-goals for first iteration

Do not require:
- full editorial/manual curation
- per-item hand pinning for `Vandaag` or `Week`
- real-time reranking on every request
- a perfect ranking algorithm from day one

The first version should be:
- automated
- inspectable
- stable
- easy to tune later

## 10. Sharper Implementation Plan

### Data model

Keep the current article-based `frontpage_items` mechanism in place for
`Uitgelicht` in the first step, to avoid an abrupt migration.

Add a new generic lane table for `Vandaag` and `Week`.

Recommended direction:

- `news_lane_items`
  - `id`
  - `lane` (`today`, `week`)
  - `article_id` nullable
  - `story_id` nullable
  - `window_start`
  - `window_end`
  - `rank_score`
  - `freshness_score`
  - `blend_score`
  - `wins`
  - `losses`
  - `similars`
  - `preference_wins`
  - `preference_losses`
  - `comparisons`
  - `computed_at`
  - `removed_at`
  - optional `notes` / `reason_code`

Constraints:
- exactly one of `article_id` or `story_id` must be set
- one active row per `(lane, article_id)` or `(lane, story_id)`

Why not fold this into `frontpage_items`:
- `Uitgelicht` is already working
- `Vandaag` and `Week` need ranking metadata
- separating them keeps migration risk low

### Settings

Add a small settings layer, likely in `site_settings`:

- `default_public_lane`
  - admin-controlled
  - possible values later: `uitgelicht`, `today`, `week`
- `homepage_main_topic_id` or equivalent topic key
- `today_window_hours`
  - default around `42`
- `week_window_days`
  - default around `12`
- optional ranking weights:
  - `today_freshness_weight`
  - `today_rank_weight`
  - `week_freshness_weight`
  - `week_rank_weight`

For the first version, these are the truly useful settings:
- `homepage_main_topic`
- `default_public_lane`

Reason:
- experimentation still needs an explicit current homepage choice
- that choice belongs in admin settings, not in unstable URL patterns

### Candidate builder

Implement a shared service that builds ranked-lane candidates.

Suggested service shape:

- `app/services/news_lanes.py`
  - `build_today_candidates(app)`
  - `build_week_candidates(app)`
  - `rank_lane_candidates(candidates, lane)`
  - `persist_lane(lane, ranked_items)`

Candidate object should include:
- type: `article` or `story`
- id
- published/latest date
- geo scope
- topic ids
- source count
- whether it already qualifies for `Uitgelicht`
- whether it is a public `verhaal`

### Pool rules

Recommended first-pass pool rules:

For `Vandaag`:
- include all public stories whose latest member article is inside the time window
- include single articles inside the time window that qualify for `Uitgelicht`
- exclude single articles already represented by an included story

For `Week`:
- same logic, but with longer window
- consider a small bonus to stories with broader source coverage

This gives a practical hybrid without needing a complicated editorial layer.

### Ranking algorithm

Start with bounded pairwise comparisons, not a full exhaustive tournament.

Suggested first implementation:

1. Sort initial pool by a cheap seed score:
   - recency
   - geo relevance
   - source count
   - current `Uitgelicht` qualification
2. Compare only a bounded neighborhood:
   - e.g. each candidate compared against the 5-8 nearest seeded neighbors
3. For each pair, decide winner
4. Convert results into:
   - wins
   - losses
   - similars
   - soft preference bonuses
   - rank score
5. Blend with freshness into final score

This gives:
- much lower cost than all-vs-all
- enough signal for a stable ranking
- explainable admin stats

### Pairwise decision source

Do not lock this too early.

Possible implementations:

1. heuristic comparator
   - cheapest
   - deterministic
   - good for v1

2. LLM-assisted comparator
   - more nuanced
   - more expensive
   - should be bounded and cached

Recommended path:
- build comparator interface first
- start heuristic
- optionally test LLM comparator later for difficult ties

Comparator response shape should explicitly support `similar`.

Suggested shape:

```json
{
  "result": "similar",
  "preferred": "a"
}
```

or:

```json
{
  "result": "a_higher"
}
```

### Heuristic comparator input signals

Useful signals for first implementation:
- is public story vs single article
- number of distinct sources
- recency
- geo scope
- frontpage worthiness
- topic strength / always_in / always_out
- story description presence

Possible rule of thumb:
- story gets a quality bonus
- very recent local article can still outrank an older story

### Scoring interpretation

Suggested interpretation of outcomes:

- `A higher`
  - full win for A
  - full loss for B
- `B higher`
  - full win for B
  - full loss for A
- `similar`
  - no full win/loss
  - both receive similarity credit
  - may emit a merge-suggestion hint
- `similar, prefer A`
  - both receive similarity credit
  - A gets a small soft bonus
  - may emit a merge-suggestion hint
- `similar, prefer B`
  - both receive similarity credit
  - B gets a small soft bonus
  - may emit a merge-suggestion hint

This should help avoid an artificially sharp ranking while still giving the
system enough information to produce a stable order.

### Merge-suggestion side effect

If the pairwise comparator returns `similar`, the system may optionally record:

- `possible_merge = true`

This is especially interesting when:
- two single articles may really be one developing story
- two verhalen may actually be overlapping and should be reviewed
- one single article and one verhaal are so close that clustering may have
  missed a connection

Recommended first approach:
- store this only as metadata / diagnostics
- do not automatically merge based on ranking comparisons alone
- allow later reuse in admin review or clustering improvements

### Scheduler integration

Add periodic jobs rather than request-time computation.

Suggested cadence:

- recompute `Vandaag` every 30 minutes
- recompute `Week` every 2-4 hours

Do not rerank on every request.

### Routes / views

Likely additions:

- `/uitgelicht`
  - current frontpage behavior under clearer naming
- `/vandaag`
- `/week`

Homepage `/` can remain configurable:
- resolve to the admin-selected main public lane
- keep lane routes stable in their own right

For now, recommended stance:
- keep `/` as a stable entry URL
- let admin choose which main themed view it serves
- keep `Uitgelicht`, `Vandaag`, and `Week` available on their own stable routes

Important:
- do not rely on `/?topic=...` for primary public navigation
- query parameters are not the right long-term shape for main-view identity

### Templates

Reuse the existing article/story-card rendering pattern where possible.

Likely minimal additions:
- new lane template modeled on the current overview pages
- lane label in header/nav
- small explanation text:
  - `Vandaag`: laatste 36-48 uur, gerangschikt op relevantie
  - `Week`: laatste 10-14 dagen, gerangschikt op belang

### Admin visibility

Add a small preview/debug page before exposing too much tuning UI.

Useful first diagnostics:
- lane
- item type
- title
- latest timestamp
- source count
- wins / losses
- similars
- soft preference wins / losses
- possible merge hints
- rank score
- freshness score
- final score

This will matter quickly because ranking disputes will otherwise become opaque.

### Migration strategy

Implement in this order:

1. Rename visible frontpage language to `Uitgelicht`
2. Add topic setting for homepage/main topic
3. Add lane data model for `Vandaag` and `Week`
4. Build candidate service
5. Persist and preview `Vandaag`
6. Expose `Vandaag` publicly
7. Extend same machinery to `Week`

### First implementation boundary

Do not try to solve all of these at once:
- lane rename
- topic control
- generic lane persistence
- pairwise ranking
- admin diagnostics

The safest first delivery is:
- `Uitgelicht` rename
- topic setting
- `Vandaag` only
- heuristic pairwise ranking
- persisted results

## 11. Experiment-first note

These lanes should be treated as experiments in presentation and ranking logic.

Primary goal:
- learn what produces the best public view of the news

Not primary goal:
- freezing the long-term homepage structure immediately

So the intended flow is:

1. build themed views
2. test how they feel in practice
3. inspect ranking/debug output
4. compare stability and usefulness
5. let admin choose which stable main view is currently `/`
6. keep the underlying lane URLs stable while that choice changes

---

*Footnote: drafted on 2026-03-30 using Codex on GPT-5.*
