<h1 align="center">Long Catch</h1>

<p align="center">
  <strong>An interactive 3D explorer for front-crawl stroke technique.</strong><br>
  Shape the stroke, induce common faults, and see how each change affects the
  swimmer and their distance per stroke.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12 or later">
  <img src="https://img.shields.io/badge/UI-NiceGUI-5898FF" alt="User interface built with NiceGUI">
  <img src="https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white" alt="Tests use pytest">
  <img src="https://img.shields.io/badge/lint-Ruff-D7FF64?logo=ruff&logoColor=black" alt="Linting with Ruff">
</p>

<p align="center">
  <img src="docs/screenshots/hero.png" alt="Long Catch showing a swimmer mid-pull with hand trails and the stroke controls panel" width="900">
</p>

## Overview

Long Catch is a local web app built with Python and
[NiceGUI](https://nicegui.io). A procedural swimmer animates a full stroke
cycle in real time. Every control changes the motion, and the stroke metrics
update as you go. It runs entirely on your machine. There are no accounts,
external services or network assets.

## Gallery

<table>
  <tr>
    <td align="center" width="33%">
      <img src="docs/screenshots/split-view.png" alt="Split view with an underwater camera and motion trails for hands and feet" width="300"><br>
      <sub><b>Split view</b>: an underwater camera beside the orbit view, with motion trails for the hands and feet.</sub>
    </td>
    <td align="center" width="33%">
      <img src="docs/screenshots/stroke-faults.png" alt="Short slipping stroke with crossover, sinking legs and snaking faults enabled" width="300"><br>
      <sub><b>Stroke faults</b>: crossover, sinking legs and snaking together, each with a coaching cue.</sub>
    </td>
    <td align="center" width="33%">
      <img src="docs/screenshots/high-elbow-catch.png" alt="Underwater close-up of a high-elbow catch" width="300"><br>
      <sub><b>High-elbow catch</b>: the forearm sets as a vertical paddle early in the pull.</sub>
    </td>
  </tr>
</table>

## Features

| Area | What it does |
| --- | --- |
| **Stroke controls** | Stroke rate, catch quality, body roll, slip, stroke depth, entry angle, drive balance and kick amplitude. |
| **Presets** | Long power, Long light, Compact connected and Short slipping. Each one is a distinct starting point. |
| **Stroke faults** | Crossover, over-rotation, over-extension, flat hips, sinking legs, snaking, knee kick and spinning arms. Combine them freely; each adds a short coaching cue. |
| **Water feedback** | Hands and forearms turn teal when holding water and coral when slipping. Amber shows the selected muscle emphasis. |
| **Cameras** | Orbit freely, or add a second Top, Side, Front or Below view in split view. |
| **Pool** | A gently moving water surface with a bow wave at the head, over a tiled floor with drifting caustics. |
| **Water reaction** | The water responds to the swimmer's measured motion. Hand entries throw spray and send out ripples, the recovering hand drips, entry air and a slipping hand release bubbles, the kick churns the surface by the feet, and a V-shaped wake trails the body. It follows the controls: a faster rate or steeper entry splashes harder, slip adds bubbles and a bigger kick adds wash. Visual only; the metrics are unaffected. |
| **Lighting** | Neutral white light with a strong main light from above and a faint cool rim light from behind, for strong colours and clear shading against the dark water. No shadows, so it stays light to render. |
| **Natural motion** | Breathing every third stroke on alternating sides: the head turns as that arm starts its recovery and is back down before the hand enters. Also a steady head, a slight body heave, and small stroke-to-stroke and kick-to-kick variation. Visual only; the metrics are unaffected. |
| **Motion trails** | Fading trails for the hands, feet or both, adjustable from 0.5 to 5 seconds. |
| **Stroke metrics** | Distance per stroke, strokes per 25 m and time per 25 m, updated live. |
| **Timeline** | Scrub or step through entry, catch, pull, finish and recovery, at ¼×, ½× or 1× speed. |

## Quick start

**Requirements:** Python 3.12.

```bash
# Linux / macOS
python3.12 -m venv .venv
source .venv/bin/activate

# Windows (Git Bash)
py -3.12 -m venv .venv
source .venv/Scripts/activate

python -m pip install -r requirements.txt
python main.py
```

Open <http://127.0.0.1:8080>. Leave the terminal running while you use the
app, then press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop the server.

## Usage

### Shape the stroke

1. Pick a **preset** to load a starting stroke. Editing any control after that
   switches the label to **Custom**.
2. Tune **stroke rate**, **catch quality**, **body roll**, **slip** and
   **drive balance**. Each one changes the stroke metrics.
3. Use **stroke depth** (close to the body or deep), **entry angle** (from
   0° near the surface to 40° toward the pool floor) and **kick amplitude** to
   change the shape of the motion.
4. Turn on one or more **stroke faults** to see them on the swimmer.
   **Clear** turns them all off.

A complete arm cycle is two strokes, with each hand entry counting as one.
Slip lowers the distance per stroke, and extra drive can't make up for a poor
catch.

### Inspect the motion

- Drag the scene to orbit and scroll to zoom.
- Drag the timeline to scrub through the right arm's phases. The cards at the
  top show the current phase of each arm.
- In the **View** card, turn on split view, choose a second camera, and pick
  a trail type and trail length.
- Trails pause with the animation and clear when you step or scrub.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| <kbd>Space</kbd> | Play or pause |
| <kbd>←</kbd> / <kbd>→</kbd> | Step through the stroke |
| <kbd>1</kbd>–<kbd>4</kbd> | Select a preset |
| <kbd>C</kbd> | Reset the camera |
| <kbd>V</kbd> | Toggle split view |

Shortcuts don't work while a slider has focus.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q        # model tests
ruff check .               # lint
ruff format --check .      # formatting
```

### Architecture

- **`long_catch/model.py`**: pure, UI-free stroke maths, including settings,
  phase timing, faults and metrics. This is the part covered by the tests.
- **`long_catch/app.py`**: the NiceGUI page. It owns the settings and sends
  the render parameters to the browser.
- **`long_catch/static/engine.js`**: the browser animation loop. It owns the
  live phase, joint solving, cameras, trails, water and lighting.
- **`long_catch/swimmer.py`**: builds the procedural swimmer and pool from
  NiceGUI scene primitives.

A new stroke fault needs three entries: `model.FAULTS` (label, cue and metric
cost), `app.FAULT_ICONS`, and its visual in `engine.js`.

### Project structure

```text
.
├── long_catch/
│   ├── app.py              # NiceGUI page and controls
│   ├── engine.py           # Browser-engine setup
│   ├── model.py            # Stroke settings, timing and metrics
│   ├── swimmer.py          # Procedural swimmer and pool geometry
│   ├── theme.py            # Palette and stylesheet loading
│   └── static/
│       ├── app.css         # Layout and component styles
│       └── engine.js       # Animation, camera, trails and joint solver
├── tests/
│   └── test_model.py
├── docs/
│   └── screenshots/        # Images used in this README
├── main.py                 # Application entry point
├── AGENTS.md               # Rules and architecture notes for coding agents
├── pyproject.toml          # Project metadata, pytest and Ruff settings
├── requirements.txt
└── requirements-dev.txt
```