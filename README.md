# Long Catch

Long Catch is a rapid local prototype for visualising front-crawl stroke shape.

> **Status:** working prototype. `main.py` is a thin entry point; the app is
> split into a typed, tested stroke model, a swimmer geometry builder, a
> browser animation engine, and a page controller under `long_catch/`.
> See [BUILD_SPEC.md](BUILD_SPEC.md) and [AGENTS.md](AGENTS.md).

It demonstrates:

- catch quality;
- body roll;
- hand slip;
- arm-driven versus hip-connected timing;
- adjustable flutter-kick amplitude and arm entry angle;
- switchable stroke faults (crossover, over-rotation, over-extension, snaking,
  knee kick, spinning arms) with coaching cues;
- simple estimated back, triceps, and hip/core contribution;
- rough distance-per-stroke and pace estimates.

The swimmer has a tapered torso and limbs, rounded joints, hands, feet, and
simple goggles. Fixed-length arm segments follow a two-bone joint solver with
an outward elbow guide and 8–145° elbow flexion, rather than winding the
shoulder through a full revolution. The elbow eases into full extension instead
of snapping straight, stays bent through a high-elbow pull, and leads an
elbow-high recovery while the body roll peaks at each catch. It is still a
simplified teaching model, not a validated biomechanical simulation.

All metrics and muscle colours are coaching estimates. They are not measured
EMG, force, medical, or diagnostic data.

The application is completely silent and does not use microphone or audio APIs.

## Repository layout

```text
.
├── .github/
│   ├── copilot-instructions.md               # Always-on Copilot rules
│   └── prompts/
│       ├── build-prototype.prompt.md         # Initial build (done)
│       └── future-production-refactor.prompt.md  # Stage 1 refactor (done)
├── long_catch/
│   ├── __init__.py
│   ├── app.py                                # Page controller, control specs, rendering
│   ├── engine.py                             # Python handle for the browser engine
│   ├── model.py                              # Typed settings, phases, timing, estimates
│   ├── swimmer.py                            # Procedural swimmer, water, lane ropes
│   ├── theme.py                              # Palette and stylesheet loading
│   └── static/
│       ├── app.css                           # Layout and component styles
│       └── engine.js                         # Browser animation loop and joint solver
├── tests/
│   └── test_model.py                         # pytest unit tests for the model
├── AGENTS.md                                 # Current objective and hard rules
├── BUILD_SPEC.md                             # Source-of-truth specification
├── README.md
├── pyproject.toml                            # pytest and Ruff configuration
├── requirements.txt
├── requirements-dev.txt                      # + pytest, ruff
├── .gitignore
└── main.py                                   # Entry point: registers the page and runs NiceGUI
```

## Requirements

- Python 3.12
- NiceGUI

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, use Git Bash (or WSL with the Linux commands above):

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

## Run

```bash
source .venv/Scripts/activate   # or .venv/bin/activate on Linux/WSL
python main.py
```

## Using it

- **Presets** load typical stroke shapes: Long power, Long light, Compact
  connected, Short slipping.
- **Sliders** adjust stroke rate, catch quality, body roll, slip, and drive
  balance. The estimates panel updates live.
- **Entry angle** (0–40°) sets how steeply the arm extends after the hand
  enters: 0° glides flat just under the surface, and higher values point the
  arm toward the pool floor. This changes the animation only.
- **Kick amplitude** runs from still legs (0%) to a stronger six-beat flutter
  kick (100%), including hip, knee, and ankle movement. This changes the
  animation only; the arm-stroke pace estimates do not include kicking.
- **Stroke faults** switch on common errors, alone or combined, on top of any
  preset or slider setting. Each one shows a coaching cue and costs estimated
  distance per stroke:
  - *Crossover*: hands enter past the centre line.
  - *Over-rotation*: the body rolls far past 45°, and the hips follow.
  - *Over-extension*: the arm locks straight, the shoulder shrugs, and the
    wrist brakes at the front before a late catch.
  - *Snaking*: the hips and legs sway side to side behind the chest.
  - *Knee kick*: a bicycle-style kick bent from the knees, not the hips.
  - *Spinning arms*: the arms rush the underwater phase faster than the hand
    can hold the water, so it slips. The timeline squeezes to match.
  *Clear* switches them all off.
- **Transport dock** (bottom of the 3D view): play/pause, step ±5% (stepping
  pauses playback), slow motion at ¼× or ½×, and a camera reset.
- **Phase timeline:** shows the right arm's entry, catch, pull, finish, and
  recovery (recovery starts later for longer strokes). Click or drag it to
  scrub to any point in the cycle. The arm cards at the top show both arms'
  current phases.
- **Presets** highlight when active; any slider change shows a *Custom* badge.
  Hover the ⓘ icons for what each control means.
- **Forearm and hand colour:** teal means holding water; coral means slipping.
- **Amber patches** show the estimated muscle emphasis (Back, Triceps,
  Hips/core, or Balanced).
- Drag to orbit and scroll to zoom.
- **Keyboard:** Space play/pause · ←/→ step · 1–4 presets · C reset camera
  (ignored while a slider has focus).

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check . && ruff format --check .
```

Open:

```text
http://127.0.0.1:8080
```
