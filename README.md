# Long Catch

Long Catch is a rapid local prototype for visualising front-crawl stroke shape.

> **Status:** working prototype. The NiceGUI app and the browser animation live
> in `main.py`; the typed, tested stroke model lives in `long_catch/model.py`
> (Stage 1 refactor done). See [BUILD_SPEC.md](BUILD_SPEC.md) and [AGENTS.md](AGENTS.md).

It demonstrates:

- catch quality;
- body roll;
- hand slip;
- arm-driven versus hip-connected timing;
- adjustable flutter-kick amplitude;
- simple estimated back, triceps, and hip/core contribution;
- rough distance-per-stroke and pace estimates.

The swimmer has a tapered torso and limbs, rounded joints, hands, feet, and
simple goggles. Fixed-length arm segments follow a two-bone joint solver with
an outward elbow guide and 8–145° elbow flexion, rather than winding the
shoulder through a full revolution. It is still a simplified teaching model,
not a validated biomechanical simulation.

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
│   └── model.py                              # Typed settings, phases, timing, estimates
├── tests/
│   └── test_model.py                         # pytest unit tests for the model
├── AGENTS.md                                 # Current objective and hard rules
├── BUILD_SPEC.md                             # Source-of-truth specification
├── README.md
├── pyproject.toml                            # pytest and Ruff configuration
├── requirements.txt
├── requirements-dev.txt                      # + pytest, ruff
├── .gitignore
└── main.py                                   # NiceGUI page, 3D swimmer, browser animation loop
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
- **Kick amplitude** runs from still legs (0%) to a stronger six-beat flutter
  kick (100%), including hip, knee, and ankle movement. This changes the
  animation only; the arm-stroke pace estimates do not include kicking.
- **Phase stepping:** Pause the animation, then use **− 5%** and **+ 5%** to
  inspect the stroke cycle in small increments. Stepping automatically pauses
  playback.
- **Forearm and hand colour:** teal means holding water; coral means slipping.
- **Amber patches** show the estimated muscle emphasis (Back, Triceps,
  Hips/core, or Balanced).
- Drag to orbit and scroll to zoom. Use Pause to freeze the stroke at any phase.

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
