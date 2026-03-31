# AGENTS.md

Shared agent entrypoint for this repository.

Use this file as the first stop for OpenAI/Codex, Claude, Gemini, or any other coding agent.

## Read Order

1. `docs/PROJECT_STATE.yaml`
2. `docs/PROJECT_META.md`
3. `NOTES.md`
4. task-specific docs linked from those files

## Purpose Split

- `AGENTS.md`: top-level compatibility entrypoint
- `docs/PROJECT_STATE.yaml`: canonical structured state for progress, goals, bugs, and todos
- `docs/PROJECT_META.md`: deeper agent handover, constraints, git context, open questions
- `NOTES.md`: practical human-facing repo instructions and runtime notes

## Working Rules

- Assume `dev` is the working branch and `main` is live/stable unless docs say otherwise.
- Do not disturb the running instance from `dev`.
- Prefer small, scoped changes.
- Do not sweep unrelated untracked files into commits.
- Keep `docs/PROJECT_STATE.yaml` and `docs/PROJECT_META.md` current when making substantial progress.

## Current Focus

See `docs/PROJECT_STATE.yaml` for the canonical current focus.

At the time this file was added, the main product direction was:
- evolve the current frontpage into stable lane concepts
- keep homepage routing stable while experimentation continues
- preserve an agent-friendly handover trail in-repo instead of only in chat history

## Compatibility Notes

- `CLAUDE.md` and `GEMINI.md` mirror this entrypoint and should stay aligned.
- Prefer referencing shared source-of-truth files instead of duplicating status across vendor-specific files.
