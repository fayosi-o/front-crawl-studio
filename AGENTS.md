# Long Catch agent instructions

Long Catch is a silent front-crawl teaching app: Python 3.12 and NiceGUI serve
a procedural 3D swimmer. Locally it runs on a random free port (8100–8899; `LONG_CATCH_PORT` pins one) with no login; on
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
  downbeat with each catch drives the hip roll).
- The estimates (`model.estimate_metrics`) take the whole `StrokeSettings` and
  the active faults: hold (catch and slip after faults and `rate_slip`, kept by
  `pull_shape`), stroke length (`path_length`, one curve for the whole rate
  range), thrust against drag (distance per stroke falls with the square root of
  the rate), momentum (`drive_seconds`, `momentum_carry` with the body's drag),
  body drag (`body_drag`: faults, `roll_drag`, `head_drag`, `kick_drag`, and `speed_drag`, the wave-making loss above the default pace, per sqrt of height, so slower strokes keep their calibration), `kick_thrust`,
  each fault's lost `push`, and height. Effort (`work_rate`) is scaled to
  `EFFORT_SPRINT` and counts the stroke's own push, so drag faults don't lower
  it. Entry angle and the breathing pattern on its own are visual only;
  breathing matters through **Head lift**, and a kick through **Sinking legs**.
- Height scales the stroke (estimates) and the whole swimmer (`scale` in the
  render params). Presets set the stroke, not the swimmer: `preset_for` keeps
  the height and `matching_preset` ignores it. Presets run from most to least
  efficient by SWOLF.
- Drills are data in `model.DRILLS` and visual only: `engine.js` remaps the
  cycle clock onto each arm (`drillArms`), and catch-up also doubles the cycle
  (`cycleScale`) and shifts the body timing (`bodyPhase`). Races always swim
  the full stroke.
- "Fix first" coaching lives in `model.advice`: it scores single changes with
  the same estimate as the header and never changes the stroke rate.

Three entries in `model.FAULTS` are good form, not errors (`Fault.good`): **Wrist press**
(more catch, less slip; the palm and wrist turn back, and it removes most of the Dropped elbow sag) and
**Shoulder reach** (`reach`: a little more distance; the shoulder and hand reach forward) and
**Hip finish & roll** (`push` < 0; the hand finishes further back and the hips roll with the shoulders). They use the same
switch and `render_params()['faults']`, sit under "Good form" in the panel, are not counted as faults and
never appear in "Fix first".
The **Water flow** view (`ViewState.flow`, `updateFlow` in `engine.js`, visual only) releases tracers at each pulling palm:
the share that holds rides back with the hand (teal) and the slipping share spills sideways (red), read from the same
per-arm slip as the hand colour plus the palm's sideways sweep.
Turning it on also opens the split view on the **Hand** angle (`VIEWS.hand`), a close-up that follows the deeper wrist;
with Water flow on it holds a steady frame on the pulling side's stroke instead of chasing the hand.
The **Catch focus** view (`ViewState.catch_focus`, `catchFocusEnv`/`showFocus` in `engine.js`, visual only) slows the stroke
clock to a fifth through each hand's catch and early pull (eased at both edges), zooms the second camera in and opens the
split view on the Hand angle. A line from elbow to wrist shows the forearm against vertical, with the angle in the arm
card: about 75° for the default pull, about 98° with a dropped elbow.
The **Anchor** view (`ViewState.anchor`, `showAnchor` in `engine.js`, visual only) plants a pin in the water where each hand
catches, drifting back at swim speed, with a line to the hand: short and teal when the hand holds, long and red when it slides.
**Keep anchor pins** (`ViewState.anchor_keep`, `leavePin`/`showKept`) leaves each stroke's final pin in the water, coloured by its
slide, for seven seconds (ten at most) so the body visibly swims past a line of anchors. Catch quality, Slip and Glide
length are the controls for how early and firmly the hand sets.
The **Cross-body link** view (`ViewState.chain`, `showChain` in `engine.js`, visual only) stretches a band from each
shoulder to the opposite hip that loads with that arm's felt load; its colour follows drive and the faults that break
the diagonal chain (Flat hips, **Same-side kick**, Crossover, Snaking, Early rotation). Same-side kick swaps the leg
timing so the downbeat lands with the same-side catch and drops the kick-driven roll (`kickTiming`).
A pulse runs up each band from the opposite leg's downbeat (`m.kickPulse`, set in `poseLegs`) and fades when it
reaches a hand that is out of the water.
The same link (`coreLink` in `engine.js`) drives the physics: a loose core leaks up to 35% of each pull's forward force into a
trunk twist (`moveThroughWater`) and a chest-versus-hip counter-yaw (`poseSwimmer`). It is zero when fully connected. The flutter kick uses the same phase (`catchDelay + KICK_START`) as the two-beat.
**Head position** (`head`, degrees from the spine line, 0 = eyes on the floor) is a slider, not a fault: inside
`HEAD_BAND` (0–15°) it is free; lifted, `head_drag` costs up to `HEAD_HIGH_COST` (scaled with pace like Sinking legs),
and tucked up to `HEAD_LOW_COST`. Fix first offers "Level the head". In `engine.js` (`headOff`) it tilts the head,
pitches the chest and legs (lifted: hips sink; buried: front dives, hips rise), grows the bow wave and, outside the
band, shows a coral gaze line from the goggles (`showGaze`, a child of the head).
The push path has three switches that only shift the hand's height in `arm()` (`dy`): **Pressing down** (a fault),
**Parallel push** and **Late upsweep** (good form, `push` < 0).

**Back arch** (`arch`, 0–30°) is a slider too: the chest leans up and out from hips that hold their place. 0–8° is free; more sinks the legs and adds `arch_drag`. The engine adds it to the arch that a lifted head or sinking legs already produce, eases to new values (snapping when paused) and swells it twice a stroke with the roll. An imbalanced body (high head, hollow back, sinking legs) also rocks in the water: pitch and bob twice a stroke and a small tail sway, all scaled by `imb` in `moveThroughWater` and zero when balanced.

**Hand paddles** (`paddles`) is training equipment: `good` and `kit`, listed under "Equipment". The paddled
hand holds more water (less slip, more push), feels heavier (`felt_load(..., hand_area(faults))`, so the hand
also moves more slowly through the pull) and its arm work costs `PADDLE_EFFORT` more (`work_rate`'s `arm_load`).
In `engine.js` the `padR`/`padL` plates show on the palms and the hand pressure probe gains `paddleArea`;
the fist drill takes them off.

### Adding a stroke fault

Faults are data in `model.FAULTS` (label, hint, cue, and a cost as drag, slip,
catch or lost push) and reach the browser as `render_params()['faults']`. Early
exit also moves the exit (`exit_phase(..., early=True)`); Lopsided pull weakens
only the right arm in the engine (`LOPSIDED_CATCH`); Early rotation turns the
shoulders to the next side during the push (`turnEarly` in `poseSwimmer`, capped
and zero outside the push: a phase shift of the whole roll flipped the recovery
elbow with a six-beat kick). A new fault needs:

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
  and the next catch). A slower stroke also lengthens in proportion to the hold,
  so a patient 22 spm stroke covers about 2.17 m per stroke (≈11.5 strokes per
  25 m and ≈2:06 per 100 m on the default settings); a slipping hand gains much
  less.
- A higher rate must be faster for a good catch but buy less per extra stroke,
  with no dip or jump in pace across the range, and must cost more effort. Above
  50 spm a weak catch slips, so its best rate is below the top of the range.
- A draggy body must lose more speed in the glide than a streamlined one.
- Don't present the visual overlays' numbers as measured, and don't add
  disclaimer text to the UI.

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
that blocks the agent session. Without `PORT`, it binds to `127.0.0.1` on a
random free port with no login; start it with `LONG_CATCH_PORT=8080` for the
browser checks.

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
    as its remainder shrinks;
  - a minimum share toward that hint enforced on a clear guide that points
    away from it: the elbow then swings half a turn whenever either one turns
    past the other (wide pulls at 55–62° roll did, by up to 0.34 m and 80° in
    one step). The minimum now applies only to a short guide (fading out by a
    quarter of its length), and pulls wider than 50% turn their elbow guide
    back, which stays square to an arm reaching out to the side. Gating the
    minimum on the hint's stability instead, or raising the "up" blend, made
    other settings flip: judge any change here on hundreds of random settings,
    not a handful.
- `keyed` eases to a stop at every keyframe. From the deepest point of the push
  to full extension in front, `arm()` uses `flowing` (a monotone cubic that
  keeps moving through keys and never overshoots), so the hand never pauses at
  the hip or mid-recovery. Keep the pull-to-finish sweep's `smooth` ending:
  letting the push end still moving lowers its peak hand speed, and with it the
  visible surge that `browser_motion.js` checks. The recovery wrist starts and
  ends straight, so the hand doesn't snap at the exit or entry.
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
  smooth humps of about 0.03 m per step. For the arm solver, also sweep a few
  hundred random settings (width, roll, catch, slip, depth, entry, rate, faults,
  drills) and compare counts with the committed code: one fix often moves a
  flip to other settings. Known leftovers are stacked faults at near-maximum
  roll with a very wide pull (for example Over-rotation plus Dropped elbow at
  77% width and 60° roll), and the forearm-twist fold when the palm target runs
  along the forearm under extreme roll.
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
