# Long Catch

Long Catch is a local, visual front-crawl teaching prototype. Adjust the
stroke, watch a procedural swimmer move, and compare the resulting coaching
estimates. It runs in a browser but is served locally by Python and NiceGUI.

> **Model limitations:** the swimmer and its estimates are illustrative, not a
> validated biomechanical simulation. Muscle colours are teaching estimates,
> not measured EMG, force, medical, or diagnostic data. The application is
> completely silent and does not use microphone or audio APIs.

## What you can explore

- Four stroke presets, plus controls for stroke rate, catch quality, body roll,
  slip, drive balance, entry angle, and kick amplitude.
- Eight switchable stroke faults, individually or in combination, with
  coaching cues: crossover, over-rotation, over-extension, flat hips, sinking
  legs, snaking, knee kick, and spinning arms.
- A 3D swimmer with an adjustable muscle-emphasis overlay and estimated
  distance per stroke, strokes per 25 m, and time per 25 m.
- An optional second camera (Top, Side, Front, or Below) and fading motion
  trails for the hands, feet, or both.

The arm animation uses fixed-length segments and a two-bone joint solver to
keep the shoulders and elbows within plausible ranges. This improves the
visual teaching model, but does not make it an anatomical simulation.

## Run locally

Requirements: Python 3.12.

### Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

### Windows

Use Git Bash or WSL:

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python main.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080). Keep the terminal running
while using the app; press Ctrl+C there to stop the server.

## Using the app

### Adjust the stroke

- Select **Long power**, **Long light**, **Compact connected**, or
  **Short slipping** to load a starting stroke shape. Editing a control marks
  the settings as **Custom**.
- Adjust stroke rate, catch quality, body roll, slip, and drive balance.
  Estimates update as you change them.
- Set **Entry angle** from 0° (near the surface) toward 40° (toward the pool
  floor). Change **Kick amplitude** from still legs to a stronger flutter.
  These two controls affect the animation, not the estimates.
- Enable one or more **Stroke faults** to see common form errors and their
  coaching cues. **Clear** turns all faults off.

### Inspect the motion

- Use the **View** card to enable split view and choose a second camera angle.
  Choose **Hands**, **Feet**, or **Both** for a fading ghost trail; set its
  length from 0.5 to 5 seconds.
- Drag the timeline to scrub through the right arm's entry, catch, pull,
  finish, and recovery. The cards above the swimmer show both arms' current
  phases.
- Use the transport dock to play or pause, step by ±5% of the cycle, change
  playback speed, or reset the camera. Trails freeze while paused and clear
  when stepping or scrubbing.
- Drag the swimmer view to orbit and scroll to zoom. Teal hands and forearms
  indicate holding water; coral indicates slipping. Amber patches show the
  selected estimated muscle emphasis.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| Space | Play or pause |
| ← / → | Step through the stroke |
| 1–4 | Select a preset |
| C | Reset the camera |
| V | Toggle split view |

Shortcuts are ignored while a slider has focus.

## Development

Install the optional development tools and run the checks:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
ruff format --check .
```

## Project structure

```text
.
├── long_catch/
│   ├── app.py              # NiceGUI page and controls
│   ├── engine.py           # Browser-engine setup
│   ├── model.py            # Stroke settings, timing, and estimates
│   ├── swimmer.py          # Procedural swimmer and pool geometry
│   ├── theme.py            # Palette and stylesheet loading
│   └── static/
│       ├── app.css         # Layout and component styles
│       └── engine.js       # Animation, camera, trails, and joint solver
├── tests/
│   └── test_model.py
├── main.py                 # Application entry point
├── AGENTS.md               # Rules and architecture notes for coding agents
├── pyproject.toml          # Project metadata, pytest, and Ruff settings
├── requirements.txt
└── requirements-dev.txt
```
