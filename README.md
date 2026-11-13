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
update when you change the pace or efficiency. Switch to **Race** to compare
two independent setups over 25–100 m. It runs entirely on your machine. There are no accounts,
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
| **Stroke controls** | Rate, catch, slip and drive stay visible, with estimates just above them. Expand **Motion details** for roll, depth, entry and kick. Both modes use the same controls. |
| **Presets** | Long power, Long light, Compact connected and Short slipping. Each one is a distinct starting point. |
| **Stroke faults** | Crossover, over-rotation, over-extension, flat hips, sinking legs, snaking, knee kick and spinning arms. Combine them freely; each adds a short coaching cue. |
| **Water feedback** | Hands and forearms turn teal when holding water and coral when slipping. Amber shows the selected muscle emphasis. |
| **Cameras** | Orbit freely, or add a second Top, Side, Front or Below view in split view. |
| **Pool** | A gently moving water surface with subtle streaks that flow backward at swim speed, a bow wave at the head, and a tiled floor with drifting caustics. |
| **Water reaction** | The water responds to the swimmer's measured motion. Hand entries throw spray and send out ripples, the recovering hand drips, entry air and a slipping hand release bubbles, the kick churns the surface by the feet, and a V-shaped wake trails the body. It follows the controls: a faster rate or steeper entry splashes harder, slip adds bubbles and a bigger kick adds wash. Visual only; the metrics are unaffected. |
| **Lighting** | Neutral white light with a strong main light from above and a faint cool rim light from behind, for strong colours and clear shading against the dark water. No shadows, so it stays light to render. |
| **Natural motion** | Breathing every third stroke on alternating sides: the head turns as that arm starts its recovery and is back down before the hand enters. Also a steady head, a slight body heave, and small stroke-to-stroke and kick-to-kick variation. Visual only; the metrics are unaffected. |
| **Motion trails** | Fading trails for the hands, feet or both, adjustable from 0.5 to 5 seconds. |
| **Stroke metrics** | Distance per stroke, strokes per 25 m and time per 25 m, updated live. |
| **Race lab** | A separate tab for 25, 50 or 100 m races with one or two independently configured swimmers. Compare strokes in colour-coded follow cameras and distance tracks, see the live distance lead, then finish times and the winning margin. |
| **Pace and waterline** | Slower swimmers settle a little deeper, especially at the hips; faster swimmers ride slightly higher. A bounded, smoothly damped buoyancy effect follows the estimated pace in both modes without changing the speed calculations. |
| **Timeline** | Scrub or step through entry, catch, pull, push, finish and recovery, at ¼×, ½× or 1× speed. The underwater sweep flows from pulling beneath the chest into a rearward push toward the hip before release. |

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
2. Tune **stroke rate**, **catch quality**, **slip** and **drive balance**.
   The estimates above the controls update immediately.
3. Expand **Motion details** for **body roll**, **stroke depth** (close to the
   body or deep), **entry angle** (0° near the surface to 40° toward the pool
   floor) and **kick amplitude**. These change motion, not estimated speed.
4. Turn on one or more **stroke faults** to see them on the swimmer.
   **Clear** turns them all off.

A complete arm cycle is two strokes, with each hand entry counting as one.
Slip lowers the distance per stroke, and extra drive can't make up for a poor
catch.

### Inspect the motion

- Drag the scene to orbit and scroll to zoom.
- Drag the timeline to pause and inspect the right arm's phases. The cards at
  the top show the current phase of each arm. With the timeline focused,
  arrow keys step 5%; Home/End seek to the beginning/end of the cycle.
  Press **Play** to resume.
- **Pull** brings the hand under the chest; **Push** extends the arm back toward
  the hip while the hand remains submerged. **Finish** releases the hand before
  recovery. They share the original cycle duration rather than adding a stroke.
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

Global shortcuts leave sliders, tabs and text fields alone. The timeline has
its own arrow-key and Home/End controls.

### Race two setups

1. Open the **Race** tab and choose **25 m**, **50 m**, or **100 m**.
   Choose **Solo** for a single-swimmer trial or **Two swimmers** to compare.
2. Select **Swimmer A** or **Swimmer B** in the panel. Each has independent
   presets, all eight stroke controls, and stroke faults. Caps and distance
   tracks are teal for A and amber for B.
3. Use **Use studio setup** to copy the original studio's stroke and faults to
   the selected swimmer, or **Copy A to B** (and vice versa) for a like-for-like
   baseline before adjusting one setting.
4. **Start race**, pause/resume with the button or Space, and **Reset race** to
   return to the start. Playback at **1x**, **2x**, or **4x** changes how quickly
   you watch, not the simulated finish times.
5. Both lanes start together. The cameras follow each swimmer so the stroke
   stays visible; the shared distance tracks show who is ahead. Each swimmer
   stops at the selected distance, with finish order, time and winning margin.

Changing a setup or distance/swimmer count resets the race. Reapplying an
identical setup, or selecting which swimmer to edit, does not. The editor heading
identifies A or B in its lane colour; edited presets are labelled **Custom**.
Leaving the Race tab pauses the race; returning
lets you resume it. Studio settings, playback state and cycle position are
preserved independently.

Race times use the same steady-speed estimates as the studio, including fault
penalties. These are continuous swims: no dive, wall turns or fatigue model.
Stroke depth, entry angle and kick amplitude still change motion rather than
the estimated speed. Waterline support is a lightweight visual approximation,
not a fluid simulation; water effects never change the race result.

### Three quick experiments

Open a walkthrough below. The pictures are captured from the running app;
the existing gallery above shows more stroke and fault examples.

<details>
<summary><b>Compare two strokes over 50 m</b></summary>

In **Race**, leave A on **Long power** and B on **Short slipping**. Start at
**1x** to watch the difference, or use **4x** to reach the result sooner.
The distance lead and finish margin compare the same start and distance.
For a controlled experiment, copy A to B, then change just B's slip.

<img src="docs/screenshots/race-comparison.png" alt="Race lab's teal and amber follow cameras comparing Long power with Short slipping" width="700">

</details>

<details>
<summary><b>Inspect the underwater push</b></summary>

In **Stroke studio**, choose **Long power**, drag the timeline to **Push**
(about 60%), and select **Triceps**. Scrubbing pauses the swimmer so you can
orbit around the hand moving back toward the hip. Use the arrow keys to step
through its release, then press **Play**.

<img src="docs/screenshots/push-inspection.png" alt="Paused swimmer during the underwater push with the Push timeline segment selected" width="700">

</details>

<details>
<summary><b>Check the catch from below</b></summary>

Enable **Split view**, choose **Below**, and turn on **Hands** trails.
Play a cycle, then pause or scrub to **Catch**. The second camera makes the
forearm's position easier to compare with the orbit view. Try **Crossover**
to see how the entry moves across the centre line.

<img src="docs/screenshots/below-catch.png" alt="Split orbit and below-water views of the catch with hand trails enabled" width="700">

</details>

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q        # model tests
ruff check .               # lint
ruff format --check .      # formatting
```

### Focused test scope

The model suite has **32 cases**, down from 49 (**about one-third fewer**).
Cases were ranked by regression value:

| Priority | Decision |
| --- | --- |
| **Keep: domain rules and regressions** | Stroke/cycle timing, Push boundaries, slip/catch/drive relationships, fault costs and stacking, preset ranking, race finish math and ties, visual-only controls, bounded buoyancy, render-parameter bounds and input validation (settings, emphasis, playback, race distance and swimmer count). |
| **Trim: equivalent inputs** | Extra linear race distances, ordinary phase samples and basic duration formatting. Retain boundary, wrap, minute-rollover and invalid-input representatives; related invalid inputs are checked inside one case. |
| **Remove: low-signal checks** | A duplicate fixed cycle duration and simple overlay/holding accessor checks. |

These are model tests, not browser automation. For UI changes, also exercise
both tabs, all eight controls, lane isolation, pause/reset, scrubbing, split
cameras and narrow layouts. Hidden scenes are throttled to 1 fps.

### Architecture

- **`long_catch/model.py`**: pure, UI-free stroke maths, including settings,
  phase timing, faults and metrics. This is the part covered by the tests.
- **`long_catch/app.py`**: the NiceGUI page. It owns the settings and sends
  the render parameters to the browser.
- **`long_catch/static/engine.js`**: the browser animation loop. It owns the
  live phase, joint solving, cameras, trails, water and lighting. The race reuses
  independent instances of this engine rather than duplicating the animation.
- **`long_catch/static/race.js`**: one shared race clock drives both lanes,
  clamps each swimmer at the finish, and updates distance tracks and results.
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
│   ├── model.py            # Stroke settings, metrics, race inputs and buoyancy targets
│   ├── swimmer.py          # Procedural swimmer and pool geometry
│   ├── theme.py            # Palette and stylesheet loading
│   └── static/
│       ├── app.css         # Layout and component styles
│       ├── engine.js       # Animation, camera, trails and joint solver
│       └── race.js         # Shared race clock and results
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