# Long Catch agent instructions

Long Catch is a silent, local front-crawl teaching app: Python 3.12 and NiceGUI
serve a procedural 3D swimmer at `127.0.0.1:8080`. See `README.md` for features.

## Architecture

- `main.py` is a thin entry point. Keep it that way.
- `long_catch/model.py` is pure and UI-free: settings, phases, timing, faults,
  and estimates. All maths that can be unit tested lives here.
- `long_catch/app.py` owns per-client state (`ViewState`) and the NiceGUI page.
- `long_catch/static/engine.js` owns the live cycle phase and every per-frame
  pose. Python sends settings via `BrowserEngine` (`engine.py`); the browser
  never sends state back. Keyboard shortcuts click the matching buttons so
  Python stays the single owner of settings.
- `long_catch/swimmer.py` builds the scene once and records the ids of objects
  the engine animates.
- Scene coordinates: head towards +x, z up, right side towards -y, water
  surface at z = 0.

### Adding a stroke fault

Faults are data in `model.FAULTS` (label, hint, cue, metric cost) and reach the
browser as `render_params()['faults']`. A new fault needs:

1. an entry in `model.FAULTS`;
2. an icon in `app.FAULT_ICONS`;
3. its visual effect in `static/engine.js`.

## Domain rules

- Every hand entry is one stroke; a right-and-left arm cycle is two strokes.
- Cycle duration is `120 / stroke_rate` seconds.
- More slip must reduce estimated distance per stroke.
- More drive must not compensate for a poor catch or heavy slip.
- Every fault must cost estimated distance per stroke.
- Muscle highlighting is an estimated teaching overlay, not EMG or medical
  data. Never present any number as measured.

## Hard constraints

- Python 3.12 and NiceGUI with `ui.scene`; no Node.js, npm, React, databases,
  cloud services, CDNs, or downloaded models.
- No sound, voice, speech, microphone, AudioContext, mute, or volume features.
- The swimmer is a simple volumetric human built from primitives: not a stick
  figure and not realistic anatomy.
- Don't add pages, persistence, or services unless asked.

## Checks

Use Git Bash (or WSL) for the virtual environment, not PowerShell:

```bash
source .venv/Scripts/activate
ruff check . && ruff format --check .
python -m pytest -q
```

## Running the server

`python main.py` never exits. Never run it in a synchronous or attached shell;
that blocks the agent session.

- Start it detached, check it with one HTTP request to
  `http://127.0.0.1:8080/`, then move on. Don't poll it.
- Before restarting, stop the previous server by its PID. Never kill
  processes by name.
- The page inlines `app.css` and `engine.js` at startup, so restart the server
  after editing either file.
- Verify UI changes in the browser before claiming success.
