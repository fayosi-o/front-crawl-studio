# AGENTS.md

Long Catch: a silent, local visual prototype for front-crawl stroke shape,
built with Python 3.12 and NiceGUI. No application code exists yet.

## Read first

1. `docs/BUILD_SPEC.md` — source of truth for scope, model behaviour,
   presets, estimate formulas, style, and the acceptance checklist.
2. `.github/copilot-instructions.md` — always-on coding rules.
3. `.github/instructions/*.instructions.md` — path-scoped rules
   (for example, browser JavaScript under `long_catch/static/js/`).

## Task prompts

Prompts live in `.github/prompts/`. Run exactly one at a time:

- `build-prototype.prompt.md` — the single-file `main.py` visual spike
  (BUILD_SPEC §8).
- `stage-1-core-models.prompt.md` — typed models, phase maths, timing,
  formatting, and pytest tests only. No UI.

These two paths take different routes. The Stage 1 prompt asks for typed
models, pytest, and Ruff. BUILD_SPEC instead calls for one `main.py` and no
extensive test suite. Let the active prompt decide that task's scope. For
anything else, follow BUILD_SPEC.

## Non-negotiables

- The app is completely silent: no audio, speech, microphone, or media APIs.
- No Node.js, npm, CDNs, databases, cloud services, or external assets.
- All metrics and muscle colours are labelled as estimates, never EMG or
  medical data.
- Do not add features that the active prompt does not request.

## Validation

- Run the app with `python main.py` (serves on `127.0.0.1:8080`).
- If tests exist, run `python -m pytest -q`.
- If Ruff is configured, run `python -m ruff check .`.
- Never claim success without command output.

## Repository

The repository is local git only, with no remote. Do not push.
