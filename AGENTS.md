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
- Natural motion in `engine.js` (breathing, heave, small per-stroke noise) is
  visual only. It is keyed to stroke time and must never change the phase,
  timeline, or Python metrics.
- The water reaction in `engine.js` (ripples, spray, bubbles, wake, kick wash,
  the pressure view and the per-stroke surge) reads the measured limb motion and
  is also visual only: it must never feed back into the pose, phase, or metrics.
- The default stroke is a distance stroke: a two-beat kick (contralateral
  downbeat with each catch drives the hip roll). Pull width and kick timing are
  visual only.

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
- A lower stroke rate must lower momentum carry (longer glide between the push
  and the next catch) and with it distance per stroke.
- Muscle highlighting is an illustrative overlay. Don't present numbers as
  measured, and don't add disclaimer text to the UI.

## Hard constraints

- Python 3.12 and NiceGUI with `ui.scene`; no Node.js, npm, React, databases,
  CDNs, or downloaded models. Render hosting is configured by `render.yaml`;
  don't add other cloud services unless asked.
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
that blocks the agent session. Without `PORT`, it binds to `127.0.0.1:8080`;
when Render sets `PORT`, it binds to `0.0.0.0` on that port.

- Start it detached, check it with one HTTP request to
  `http://127.0.0.1:8080/`, then move on. Don't poll it.
- Before restarting, stop the previous server by its PID. Never kill
  processes by name.
- The page inlines `app.css` and `engine.js` at startup, so restart the server
  after editing either file.
- Verify UI changes in the browser before claiming success.

## Browser and animation checks

- On Windows, run `playwright-cli` through Git Bash or WSL to avoid the
  PowerShell execution-policy issue. If unavailable, use the shared VS Code
  browser tools.
- Use a visible page for animation checks: background tabs can throttle
  rendering and make interactions unreliable.
- Browser scripts cannot assume a global `THREE`. Reuse scene objects for
  vector and quaternion operations.
- For repeatable motion checks, use the `window.LongCatch` phase controls
  rather than wall-clock waits. Update scene world matrices before measuring
  world-space positions.
- Keep browser checks short and collect results before reloading or restarting;
  page-local helpers and unfinished evaluations can be lost. Verify server
  readiness before navigating rather than relying on a fixed delay.
- Inspect visual effects from multiple relevant views. Distinguish camera
  occlusion or low opacity from missing behaviour, and support visual checks
  with measurements where practical.
- For sudden joint flips, check degenerate direction vectors, coordinate
  frames and angle wrapping as well as keyframes. Prefer continuous
  transitions; verify full-cycle continuity across affected settings and
  faults, including extremes.
- Remove temporary debug hooks and syntax-check changed JavaScript before
  committing.
