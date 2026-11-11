# Long Catch Rapid Prototype

## 30–60 Minute Build Plan for Python 3.12, NiceGUI, and VS Code Copilot Fusion

## 1. Goal

Build a fast, working visual prototype of **Long Catch** in approximately **30–60 focused minutes**.

The prototype should answer one question:

> Can a simple animated human clearly demonstrate the difference between a long connected front-crawl stroke, a compact connected stroke, and a short slipping stroke?

This is a **visual proof of concept**, not a production application.

The swimmer should be recognisably human but intentionally simple:

- tapered torso;
- oval head;
- cylindrical upper arms and forearms;
- cylindrical thighs and lower legs;
- short flattened hands;
- small feet;
- visible shoulders and hips.

It must not be a stick figure, but it does not need realistic anatomy, skin, facial detail, fingers, or muscle deformation.

---

## 2. Prototype scope

Build one screen containing:

1. A large 3D swimmer.
2. Play and Pause.
3. Stroke-rate control.
4. Catch-quality control.
5. Body-roll control.
6. Slip control.
7. Drive-balance control.
8. Muscle emphasis selector.
9. Four stroke-strategy presets.
10. Four simple estimated statistics.

### Include

- Python 3.12.
- NiceGUI.
- NiceGUI `ui.scene`.
- One `main.py` file initially.
- A local browser interface at `127.0.0.1:8080`.
- A simple procedural swimmer.
- A continuous front-crawl cycle.
- Visible body roll.
- Visible catch and slip differences.
- Simple back, triceps, and hip/core highlighting.
- Estimated distance per stroke.
- Estimated strokes per 25 m.
- Estimated time per 25 m.

### Do not include yet

- Multiple pages.
- Count-page stopwatch.
- Length history.
- LocalStorage.
- Side-view SVG.
- Skeleton overlay.
- Anatomically shaped muscles.
- Detailed shoulder mechanics.
- Ghost arms.
- Water particles.
- Direct elbow dragging.
- Complex breathing options.
- Mobile optimisation.
- Browser automation.
- A large test suite.
- Production packaging.
- Cloud services.
- External assets.

---

## 3. Silent application requirement

Long Catch must be completely silent.

Do not add:

- voice guidance;
- speech synthesis;
- speech recognition;
- microphone access;
- music;
- entry beeps;
- sound effects;
- audio files;
- Web Audio API;
- `AudioContext`;
- mute controls;
- volume controls.

All feedback must be visual.

---

## 4. Technology

Use:

- Python 3.12;
- NiceGUI;
- NiceGUI `ui.scene`;
- plain Python calculations;
- a NiceGUI timer or a very small local browser animation function.

Do not use:

- Node.js;
- npm;
- React;
- a database;
- a backend API;
- asynchronous cloud services;
- a public CDN;
- downloaded human models.

---

## 5. Minimal project structure

This repository's root is the project folder. The prototype adds only:

```text
.
└── main.py
```

These already exist: `README.md`, `AGENTS.md`, `BUILD_SPEC.md`,
`requirements.txt`, `.gitignore`, and `.github/`.

Optional after the prototype works, and only on explicit request:

```text
tests/
└── test_calculations.py
```

Do not split the first prototype into many modules.

---

## 6. Setup from start to finish

### Step 1: Open the folder

Open this repository's root folder in VS Code. Do not create a nested
`long-catch/` folder.

### Step 2: Create a Python 3.12 environment

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

Linux or macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Confirm the version:

```bash
python --version
```

Expected:

```text
Python 3.12.x
```

### Step 3: Select the interpreter in VS Code

1. Open the Command Palette with `Ctrl+Shift+P`.
2. Choose **Python: Select Interpreter**.
3. Select the interpreter inside `.venv`.

### Step 4: Install NiceGUI

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` already lists `nicegui`.

### Step 5: Create the working files

`README.md`, `AGENTS.md`, and `.github/copilot-instructions.md` already exist.
`/build-prototype` creates `main.py`.

---

## 7. Copilot instructions

The always-on rules live in `.github/copilot-instructions.md`, so they are not
repeated here. Edit that file directly.

---

## 8. Build prompt

The build prompt lives in `.github/prompts/build-prototype.prompt.md`.

In VS Code Copilot Chat, select a high-capability model and run:

```text
/build-prototype
```

---

## 9. Required model behaviour

### Stroke cycle

Use one phase value from 0.0 to 1.0.

```python
right_phase = phase
left_phase = (phase + 0.5) % 1.0
```

Use:

```python
cycle_duration_seconds = 120.0 / stroke_rate
```

Suggested broad phase regions:

| Phase | Movement |
|---|---|
| 0.00–0.12 | Entry and reach |
| 0.12–0.30 | Elbow set and catch |
| 0.30–0.62 | Pull |
| 0.62–0.75 | Finish and exit |
| 0.75–1.00 | Recovery |

Smooth interpolation is desirable, but exact biomechanics are not required for the prototype.

### Catch-quality effect

High catch quality should:

- keep the elbow nearer the surface;
- bend the elbow earlier;
- place the forearm nearer vertical during the catch;
- colour the forearm and hand towards teal.

Low catch quality should:

- drop the elbow;
- move the whole arm backwards earlier;
- keep the forearm less vertical;
- reduce the apparent paddle shape.

### Slip effect

High slip should:

- move the hand backwards towards the feet;
- slightly fold the wrist;
- colour the hand and forearm towards coral;
- reduce estimated distance per stroke.

Low slip should:

- keep the hand relatively stable during the catch;
- let the body appear to move past the hand;
- keep the wrist firmer.

### Drive-balance effect

Low drive should:

- make motion look more shoulder and arm driven;
- reduce hip-to-shoulder timing connection.

High drive should:

- make pelvic roll lead chest roll slightly;
- connect the catch with body rotation;
- highlight the hip/core region more strongly.

Drive must not create free speed when catch quality is poor or slip is high.

---

## 10. Simple muscle highlighting

Do not draw anatomically exact muscles.

Use simple patches or segment highlights:

### Back

Highlight a broad patch on the side/rear torso during catch and pull.

### Triceps

Highlight the rear portion of the active upper arm during the finish.

### Hips/core

Highlight a belt-like waist/oblique patch and the hip region during roll.

### Balanced

Show all three at lower intensity according to phase.

Always show:

```text
Estimated contribution for this modelled stroke
```

Never show:

- measured activation;
- EMG percentage;
- muscle strength;
- joint torque;
- injury risk;
- medical diagnosis.

---

## 11. Presets

| Preset | Catch | Roll | Rate | Slip | Drive | Intended appearance |
|---|---:|---:|---:|---:|---:|---|
| Long power | 92% | 46° | 38 | 8% | 85% | Long path, connected roll, stronger highlight |
| Long light | 88% | 44° | 40 | 10% | 70% | Long but visually lighter |
| Compact connected | 82% | 42° | 48 | 14% | 68% | Shorter path, earlier exit, good rhythm |
| Short slipping | 42% | 34° | 54 | 62% | 35% | Dropped elbow, sliding hand, poor distance |

Preset selection must update:

- all control values;
- swimmer pose behaviour;
- muscle highlight;
- estimated statistics.

---

## 12. Estimate formulas

Normalise percentages to 0.0–1.0.

```python
def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def estimate_metrics(
    catch_quality: float,
    slip: float,
    drive_balance: float,
    stroke_rate: float,
) -> dict[str, float]:
    hold_quality = clamp(
        0.6 * catch_quality + 0.4 * (1.0 - slip),
        0.0,
        1.0,
    )

    connection = 0.7 + 0.3 * drive_balance
    rate_penalty = max(0.0, stroke_rate - 56.0) / 80.0

    distance_per_stroke = clamp(
        0.55
        + 0.75 * hold_quality * connection
        - 0.40 * slip
        - rate_penalty,
        0.45,
        1.40,
    )

    strokes_per_25 = 25.0 / distance_per_stroke
    seconds_per_25 = strokes_per_25 * 60.0 / stroke_rate

    return {
        'hold_quality': hold_quality,
        'distance_per_stroke': distance_per_stroke,
        'strokes_per_25': strokes_per_25,
        'seconds_per_25': seconds_per_25,
    }
```

These are visual coaching estimates, not measured swimming results.

Do not spend time calibrating them precisely during the first build. Their only immediate requirement is sensible direction:

- more slip worsens distance per stroke;
- a better catch improves distance per stroke;
- connected drive helps only when the hand holds;
- the four presets produce visibly different values.

---

## 13. Visual style

Use:

```css
--pool-bg: #08141a;
--panel-bg: #123038;
--text-main: #e7f0ea;
--text-muted: #9cb0ac;
--hold-good: #3dbea5;
--slip-bad: #e36b4f;
```

Layout:

- swimmer occupies most of the screen;
- controls sit in one compact panel;
- presets form one row or wrap cleanly;
- statistics remain visible;
- copy is short;
- avoid dashboard-style cards everywhere.

Do not spend more than approximately five minutes polishing CSS during the first pass.

---

## 14. Build stages inside the 30–60 minute window

### Stage A: Setup — 5 minutes

- Create the folder.
- Create the virtual environment.
- Install NiceGUI.
- Create `main.py`.
- Add Copilot instructions.

Completion check:

```bash
python -c "import nicegui; print('NiceGUI ready')"
```

### Stage B: Static scene — 10 minutes

Ask Copilot to create:

- one NiceGUI page;
- dark pool background;
- one `ui.scene`;
- basic swimmer geometry;
- controls and preset buttons.

Completion check:

- `python main.py` starts;
- the page opens;
- the swimmer resembles a simple human;
- controls are visible.

### Stage C: Animation — 10–15 minutes

Add:

- one phase variable;
- left/right half-cycle offset;
- arm paths;
- body roll;
- Play/Pause;
- stroke-rate control.

Completion check:

- both arms move;
- they remain half a cycle apart;
- rate changes are visible;
- body roll is visible.

### Stage D: Catch, slip, and drive — 10 minutes

Add visible effects for:

- elbow height;
- forearm angle;
- hand slip;
- wrist shape;
- hip/chest timing.

Completion check:

- 100% Catch looks clearly different from 0%;
- 100% Slip looks clearly different from 0%;
- high Drive produces more coordinated roll than low Drive.

### Stage E: Presets, highlights, and estimates — 10 minutes

Add:

- four presets;
- back/triceps/hips/balanced selector;
- simple muscle highlights;
- distance-per-stroke estimate;
- strokes-per-25 estimate;
- time-per-25 estimate.

Completion check:

- all four presets visibly differ;
- Long power looks longer than Compact connected;
- Short slipping looks least effective;
- statistics change with presets.

### Stage F: Repair and stop — 5–10 minutes

Only fix:

- startup errors;
- controls that do nothing;
- obvious broken geometry;
- presets not updating;
- Play/Pause not working;
- unreadable layout.

Do not add new features during this stage.

---

## 15. Manual acceptance checklist

The prototype is complete when all boxes are checked:

- [ ] `python main.py` starts without a traceback.
- [ ] The page opens at `127.0.0.1:8080`.
- [ ] The swimmer is recognisably human and not a stick figure.
- [ ] Play/Pause works.
- [ ] Both arms animate half a cycle apart.
- [ ] Stroke rate changes animation speed.
- [ ] Catch quality changes elbow and forearm shape.
- [ ] Slip moves the underwater hand backwards.
- [ ] Body roll changes visibly.
- [ ] Drive balance changes hip/chest connection.
- [ ] Long power looks longer and stronger than Compact connected.
- [ ] Long light has softer muscle highlighting than Long power.
- [ ] Compact connected exits earlier and cycles faster.
- [ ] Short slipping shows a dropped elbow and sliding hand.
- [ ] Muscle emphasis options change the highlighted body region.
- [ ] The contribution label says it is estimated.
- [ ] Estimated statistics change sensibly.
- [ ] There is no audio, voice, microphone, mute, or volume feature.

Stop building when these checks pass.

---

## 16. If Copilot overbuilds

Send:

```text
Stop expanding the architecture.

This is a visual spike, not a production build.

Keep the implementation in one main.py file.
Do not add more pages, services, persistence, browser tests, detailed anatomy,
or extra documentation.

Finish only:

- the basic human swimmer;
- front-crawl animation;
- five controls;
- four presets;
- simple muscle highlights;
- four estimated statistics.

Run the application and fix only blocking errors.
```

---

## 17. If the animation is broken

Send:

```text
Do not redesign the application.

Fix only the swimmer animation in main.py.

Requirements:

- right arm phase is phase;
- left arm phase is `(phase + 0.5) % 1`;
- cycle duration is `120 / stroke_rate`;
- the arm path contains entry, catch, pull, finish, and recovery;
- Catch changes elbow height and forearm angle;
- Slip moves the underwater hand towards the feet;
- Roll rotates the chest and hips around the long axis.

Prefer simple smooth movement over biomechanical detail.
Run the app after the fix.
```

---

## 18. If the model looks too much like a stick figure

Send:

```text
Improve only the swimmer's body volume.

Do not add realistic anatomy.

Use:

- a wider shoulder/chest section;
- a narrower waist;
- a visible hip section;
- thicker upper arms and thighs;
- distinct forearms and calves;
- flattened hands;
- small feet;
- an oval head.

Keep the existing animation and controls.
Do not introduce an external 3D model.
```

---

## 19. If the muscle highlighting looks too anatomical

Send:

```text
Simplify the muscle visualisation.

It should be a teaching overlay, not medical anatomy.

Use only:

- one broad back/side torso patch;
- one rear-upper-arm triceps patch per arm;
- one waist/oblique band;
- one hip patch per side.

Attach patches to the relevant body groups so they follow animation.
Label them as estimated contribution.
Do not add individual muscle insertions or medical terminology.
```

---

## 20. Optional minimal tests after the visual prototype works

Only add these if the prototype is worth keeping:

```python
def test_cycle_duration_at_40_spm():
    assert cycle_duration(40) == 3.0


def test_more_slip_reduces_distance_per_stroke():
    low_slip = estimate_metrics(0.9, 0.1, 0.7, 40)
    high_slip = estimate_metrics(0.9, 0.7, 0.7, 40)
    assert high_slip['distance_per_stroke'] < low_slip['distance_per_stroke']


def test_better_catch_improves_distance_per_stroke():
    poor = estimate_metrics(0.3, 0.1, 0.7, 40)
    good = estimate_metrics(0.9, 0.1, 0.7, 40)
    assert good['distance_per_stroke'] > poor['distance_per_stroke']


def test_outputs_are_finite():
    result = estimate_metrics(0.9, 0.1, 0.7, 40)
    assert all(math.isfinite(value) for value in result.values())
```

Do not add browser tests at this stage.

---

## 21. README

The project README is `README.md` at the repository root. Keep it in sync when
setup or run commands change.

---

## 22. What to do after the prototype

Do not automatically continue into a full build.

First use the prototype and decide:

1. Can you clearly see the difference between holding and slipping?
2. Does the long stroke look connected rather than paused?
3. Does Compact connected look shorter without looking defective?
4. Do the muscle highlights help explain the movement?
5. Is the 3D camera useful for teaching the catch?

If the answer is yes, choose only one next improvement:

- add a side view;
- improve elbow and hand paths;
- add phase stepping;
- add a manual length counter;
- add settings persistence;
- improve muscle overlays.

Do not add all of them at once.

---

## 23. Final instruction to Copilot

After the manual checklist passes, send:

```text
The rapid prototype is complete.

Do not add features.

Review main.py only for:

- obvious unused code;
- startup errors;
- controls that do nothing;
- accidental audio or microphone functionality;
- incorrect stroke-cycle timing;
- division-by-zero or invalid-number risks.

Make only necessary fixes, run the application one final time, and stop.
```
