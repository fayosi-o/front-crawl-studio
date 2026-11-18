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
  and the next catch). Below 42 spm the stroke also lengthens in proportion to
  the hold, so a patient 22 spm stroke covers about 1.95 m (≈12.8 strokes and
  ≈2:19 per 100 m on the default settings); a slipping hand gains little.
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

## Browser automation

On Windows, `playwright-cli` resolves to a `.ps1` script that PowerShell's
execution policy blocks. Never call it from PowerShell. Run it through Git
Bash or WSL so the `sh` shim is used instead:

```bash
bash -lc "playwright-cli open http://127.0.0.1:8080/"
```

If `node` itself is blocked in the agent shell, use the shared VS Code browser
(`runPlaywrightCode`) instead. For screenshots at a fixed size, open a new page
with `page.context().newPage()` and call `setViewportSize` on it.

- The shared tab is usually hidden. Hidden tabs throttle
  `requestAnimationFrame`, so clicks time out waiting for "stable" and the
  estimates don't update. Forced clicks there give false results. For any
  UI check, open a fresh visible page with `newPage()` and `setViewportSize`.
- There is no global `THREE`. In page scripts, make vectors with
  `scene.position.clone()` and quaternions with `scene.quaternion.clone()`.
- Drive the engine deterministically instead of waiting on animation:
  `L = window.LongCatch`, `L.set({...})`, then
  `L.step(ph - L.step(0)); L.advance(0)` to jump to phase `ph`. Call
  `scene.updateMatrixWorld(true)` before reading world positions. The scene
  is `getElement(<scene id>).scene`.
- Helpers defined with `page.evaluate` are lost on reload. Use
  `page.addInitScript` for helpers that must survive restarts.

## Lessons from past work

These problems cost real time before. Plan around them.

### Long browser runs

- An evaluate longer than about a minute returns a deferred result. Deferred
  results are easily lost: by a page reload, a server restart, or simply
  expiring. Split sweeps into chunks of about a minute (for example, one
  setting value per call) and return compact summaries, not per-frame logs.
- Restarting the server reloads the page and kills any in-flight evaluate.
  Finish or abandon a sweep before editing `engine.js` and restarting.
- Start each server in a new async shell id. Stop the old one by PID first
  (`Get-NetTCPConnection -LocalPort 8080 -State Listen`), then wait about 6 s
  before `page.goto`, or you get "connection refused".

### Judging visual effects

- Don't judge a faint effect from one camera. The pressure particles first
  looked missing because they were low alpha and mostly behind the body from
  the default view. Check from the Below or Side view, and measure what you
  can (for example, count live particles for a clean versus a slipping
  stroke) instead of eyeballing a screenshot.

### Arm IK in `poseArm`

- Elbow and hand "flips" (a jump in one frame) come from direction vectors
  that pass through zero length, not from the keyframes themselves:
  - a bend-direction guide nearly parallel to the shoulder→hand axis;
  - a world-referenced guide under heavy body roll, where "out and up" can
    point back along the arm;
  - a palm twist angle crossing ±180°.
- Fix these with continuous constructions: soft minimum shares, a partial
  roll, or folding the angle. Avoid `if (length < threshold)` fallbacks, which
  create a new discontinuity at the threshold.
- Verify with a sweep, not by watching. Step 1/250 to 1/500 of a cycle across
  catch, slip, width, depth, exit and faults. Flag elbow moves over 0.06 m or
  hand turns over about 25–40° in one step. Find the wrists as the two
  3-child groups that travel furthest; the elbow is `wrist.parent`. Accept
  smooth humps of about 0.03 m per step.
- Temporary debug hooks (for example `window.__dbg`) must be removed before
  committing. Run `node --check long_catch/static/engine.js` after every edit.

### Shell quirks

- In PowerShell, `git push` writes progress to stderr, which shows up as a
  red `NativeCommandError` even when the push succeeded. Read the
  `old..new main -> main` line before assuming it failed.
