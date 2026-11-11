# Long Catch agent instructions

## Current objective

The current objective is the 30–60 minute visual prototype described in
`BUILD_SPEC.md`.

Use `.github/prompts/build-prototype.prompt.md` for the initial build.

The prototype must remain in one `main.py` file until the manual acceptance
checklist passes.

## Deferred work

`.github/prompts/future-production-refactor.prompt.md` is not part of the
initial build. Do not use it unless explicitly requested after the visual
prototype works.

Do not introduce typed domain modules, a package hierarchy, Ruff, pytest,
browser-runtime files, persistence, multiple pages, or production architecture
during the prototype build.

## Hard rules

- Python 3.12 and NiceGUI.
- Run on `127.0.0.1:8080`.
- No Node.js or npm.
- No external models or CDNs.
- No sound, voice, microphone, AudioContext, mute, or volume features.
- Build a basic volumetric human, not a stick figure and not realistic anatomy.
- Count every hand entry as one stroke.
- A complete arm cycle contains two strokes.
- Cycle duration is `120 / stroke_rate`.
- More slip must reduce estimated distance per stroke.
- More drive must not compensate for poor catch or severe slip.
- Muscle highlighting is an estimated teaching overlay, not EMG or medical data.

## Completion

The prototype is complete when:

- `python main.py` starts;
- the swimmer animates;
- Play/Pause works;
- all controls visibly affect the swimmer;
- all four presets visibly differ;
- estimates update;
- no placeholder controls remain.

Run the application before claiming completion.
