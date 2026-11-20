# Long Catch agent instructions

Long Catch is a silent front-crawl teaching app: Python 3.12 and NiceGUI serve
a procedural 3D swimmer. Locally it runs at `127.0.0.1:8080` with no login; on
Render it runs behind a login (see "Running the server"). See `README.md` for
features.

These instructions are platform-neutral. Windows notes are at the end;
`CLAUDE.md` adds macOS notes for Claude Code.

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
- `long_catch/engine.py` inlines `engine.js` and `race.js` into the page and
  holds `BrowserEngine` (the studio swimmer) and `RaceEngine` (the race).
  Both send through the client they were created on, so a handler that
  deletes its own button can still reach the browser.
- `long_catch/static/race.js` runs one race clock that drives several
  independent instances of the studio engine, one per lane.
- `long_catch/theme.py` holds the colour palette and stylesheet shared by the
  scene, engine and page.
- `long_catch/auth.py` is the login for hosted mode only: an in-memory
  session middleware (`PrivateAccess`) added by `main.py`. Locally it is off.
- Scene coordinates: head towards +x, z up, right side towards -y, water
  surface at z = 0.
- Natural motion in `engine.js` (breathing, heave, small per-stroke noise) is
  visual only. It is keyed to stroke time and must never change the phase,
  timeline, or Python metrics.
- The water reaction in `engine.js` (ripples, spray, bubbles, wake, kick wash,
  the pressure view and the per-stroke surge) reads the measured limb motion and
  is also visual only: it must never feed back into the pose, phase, or metrics.
- The felt load is a sensation: the water the hand pushes back makes the arm
  feel heavier (`model.felt_load`, `load_profile`). It slows the hand through
  the heaviest water, speeds it up as the load lets go (`LOAD_DWELL`,
  `LOAD_RELEASE`) and shortens the recovery (`model.loaded_time`, mirrored
  by `underwater` in `engine.js`), so the timeline shows it, but it never
  changes buoyancy or the estimates. The HUD's Load bars show it per arm.
- The default stroke is a distance stroke: a two-beat kick (contralateral
  downbeat with each catch drives the hip roll). Pull width, kick timing and
  breathing pattern are visual only.
- Drills are data in `model.DRILLS` and visual only: `engine.js` remaps the
  cycle clock onto each arm (`drillArms`), and catch-up also doubles the cycle
  (`cycleScale`) and shifts the body timing (`bodyPhase`). Races always swim
  the full stroke.
- "Fix first" coaching lives in `model.advice`: it scores single changes with
  the same estimate as the header and never changes the stroke rate.

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
  the hold, so a patient 22 spm stroke covers about 1.97 m per stroke (≈12.7
  strokes per 25 m and ≈2:19 per 100 m on the default settings); a slipping
  hand gains little.
- Muscle highlighting is an illustrative overlay. Don't present numbers as
  measured, and don't add disclaimer text to the UI.

## Hard constraints

- Python 3.12 and NiceGUI with `ui.scene`. The app must not use Node.js, npm,
  React, databases, CDNs, or downloaded models. Node and Playwright are
  allowed for the checks only (`node --check` and the browser checks). Render hosting is configured by `render.yaml`;
  don't add other cloud services unless asked.
- No sound, voice, speech, microphone, AudioContext, mute, or volume features.
- The swimmer is a simple volumetric human built from primitives: not a stick
  figure and not realistic anatomy.
- Don't add pages, persistence, or services unless asked.

## Checks

Activate the virtual environment first (see the platform notes), then:

```bash
ruff check . && ruff format --check .
python -m pytest -q
node --check long_catch/static/engine.js
```

The browser checks are `tests/browser_estimates.js` (the header estimates
following studio and race edits, and the header layout from 1440 px down to
320 px) and `tests/browser_motion.js` (the
swimmer's motion, water reaction and a full 25 m race). Both open
`http://127.0.0.1:8080/`, so restart that server on the current code first,
then from `tests/`:

```bash
playwright-cli open about:blank
playwright-cli run-code --filename=browser_estimates.js
playwright-cli run-code --filename=browser_motion.js
playwright-cli close
```

Each prints `"checks":"passed"` or the assertion that failed. Don't copy the
scripts to another port; restart the server on 8080 instead.

Or run both from the repository root with `node tools/browser_checks.js [URL]`,
which finds Playwright and an installed Chromium itself and prints `PASS` or
`FAIL` for each; pass a URL to check a server on another port.

## Running the server

`python main.py` never exits. Never run it in a synchronous or attached shell;
that blocks the agent session. Without `PORT`, it binds to `127.0.0.1:8080`
with no login.

Setting `PORT` or `RENDER` switches on hosted mode: the server binds to
`0.0.0.0` on `PORT`, requires a login, and refuses to start unless
`APP_USERNAME`, `APP_PASSWORD_HASH` (an Argon2 hash) and `SESSION_SECRET` (32+
characters) are set. Render sets these; never set `PORT` or `RENDER` locally.
`/health` stays public. The README's "Deploy to Render" section has the setup.

- Start it detached, check it with one HTTP request to
  `http://127.0.0.1:8080/`, then move on. Don't poll it.
- Before restarting, stop the previous server by its PID. Never kill
  processes by name.
- The page inlines `app.css` and `engine.js` at startup, so restart the server
  after editing either file.
- Verify UI changes in the browser before claiming success.

## Browser automation

Use whichever browser tool your agent has: a built-in browser, the Playwright
MCP tools, or `playwright-cli`.

- Hidden tabs throttle `requestAnimationFrame`, so clicks time out waiting for
  "stable" and the estimates don't update. Forced clicks there give false
  results. For any UI check or fixed-size screenshot, open a fresh visible
  page with `page.context().newPage()` and call `setViewportSize` on it.
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

- A long synchronous evaluate blocks NiceGUI's socket, and the page reloads,
  losing helpers defined on `window`. Keep each call to about ten sweeps and
  redefine helpers at the top of each call.
- An evaluate longer than about a minute returns a deferred result. Deferred
  results are easily lost: by a page reload, a server restart, or simply
  expiring. Split sweeps into chunks of about a minute (for example, one
  setting value per call) and return compact summaries, not per-frame logs.
- Restarting the server reloads the page and kills any in-flight evaluate.
  Finish or abandon a sweep before editing `engine.js` and restarting.
- Start each server in a new background shell. Stop the old one by its PID
  first (see the platform notes), then wait about 6 s before `page.goto`, or
  you get "connection refused".

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
  - a palm twist angle crossing ±180°;
  - a hard `clamp` on a bound that releases quickly: under heavy roll the
    elbow's outward bound (`minOut`) sat at 1 and then fell fast as the elbow
    bent, swinging the bend plane, and through the palm-twist fold the hand,
    by 60–90° in one step. A `tanh` on the positive side fixed it;
  - a fallback guide that can itself run along the arm: the "out and a little
    forward" hint is parallel to a 100%-width pull, so it now blends in "up"
    as its remainder shrinks.
- Fix these with continuous constructions: soft minimum shares, a partial
  roll, or folding the angle. Avoid `if (length < threshold)` fallbacks, which
  create a new discontinuity at the threshold.
- The palm-twist fold beyond ±135° moves about 3× faster than its input, so
  any fast swing of the bend plane is amplified there. Look for the swing
  rather than retuning the fold; the normal stroke uses that range.
- Verify with a sweep, not by watching. Compare old and new code in one session
  with a temporary `window.__flag` toggle, and give every sweep a complete set
  of params: `LongCatch.set` merges, so a field left out keeps the previous
  config's value. Step 1/250 to 1/500 of a cycle across
  catch, slip, width, depth, exit and faults. Flag elbow moves over 0.06 m or
  hand turns over about 25–40° in one step. Find the wrists as the two
  3-child groups that travel furthest; the elbow is `wrist.parent`. Accept
  smooth humps of about 0.03 m per step.
- Temporary debug hooks (for example `window.__dbg`) must be removed before
  committing. Run `node --check long_catch/static/engine.js` after every edit.

## Git and deployment

- Commit and push finished work straight to `main` without asking first.
  Pushing to `main` deploys to Render, so push only after every check in
  "Checks" passes, including both browser checks.
- Never force-push `main`, rewrite its history, or push secrets.

## Windows notes

- Use Git Bash or WSL for the virtual environment, not PowerShell:
  `source .venv/Scripts/activate`.
- Find the server's PID with
  `Get-NetTCPConnection -LocalPort 8080 -State Listen`, then stop it by that
  PID.
- `playwright-cli` resolves to a `.ps1` script that PowerShell's execution
  policy blocks. Never call it from PowerShell; run it through Git Bash or WSL
  so the `sh` shim is used, for example
  `bash -lc "playwright-cli open http://127.0.0.1:8080/"`.
- If `node` itself is blocked in the agent shell, use the shared VS Code
  browser (`runPlaywrightCode`). Its tab is usually hidden, so open a fresh
  visible page as described in "Browser automation".
- In PowerShell, `git push` writes progress to stderr, which shows up as a
  red `NativeCommandError` even when the push succeeded. Read the
  `old..new main -> main` line before assuming it failed.
