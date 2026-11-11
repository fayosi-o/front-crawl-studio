---
agent: agent
description: Build the Long Catch single-file NiceGUI visual prototype (BUILD_SPEC section 8). Run with Copilot Fusion High.
---

Read `.github/copilot-instructions.md` before editing.

Create a rapid visual prototype named Long Catch.

Time-box the implementation to approximately 30–60 minutes.

Use:

- Python 3.12
- NiceGUI
- NiceGUI ui.scene
- one main.py file initially
- localhost at 127.0.0.1:8080

Do not use:

- Node.js
- npm
- a database
- cloud services
- external assets
- audio
- voice
- microphone access
- Web Audio
- media files

The objective is to prove the visual concept, not build a production app.

BUILD ONE SCREEN

The screen contains:

1. A large 3D swimmer.
2. Play/Pause.
3. A stroke-rate slider from 32 to 72 hand entries per minute.
4. Four sliders:
   - Catch quality, 0–100%.
   - Body roll, 20–62 degrees.
   - Slip, 0–100%.
   - Drive balance, 0–100%, where 0 is arm-dominant and 100 is hip-connected.
5. Four preset buttons:
   - Long power.
   - Long light.
   - Compact connected.
   - Short slipping.
6. Four estimated values:
   - Stroke rate.
   - Distance per stroke.
   - Strokes per 25 m.
   - Estimated time per 25 m.
7. A simple muscle emphasis selector:
   - Back.
   - Triceps.
   - Hips/core.
   - Balanced.

SIMPLE HUMAN MODEL

Create a deliberately simple but recognisably human swimmer using:

- a tapered or scaled capsule/cylinder torso;
- an oval head;
- cylinders or capsules for limbs;
- flattened short hands;
- small feet;
- visible shoulders and hips.

The swimmer must not be a stick figure.

Do not attempt realistic anatomy, skin, facial detail, fingers, or a
medical-grade skeleton.

ANIMATION

Create one continuous front-crawl cycle.

- Right arm uses phase 0–1.
- Left arm uses `(phase + 0.5) % 1`.
- Every hand entry counts as one stroke.
- Complete cycle duration is `120 / stroke_rate`.
- Use a NiceGUI timer or compact browser-side animation.
- Prefer a working simple animation over a complex architecture.

The stroke should visibly contain:

- entry;
- extension;
- elbow set;
- catch;
- pull;
- finish;
- recovery.

The body should roll around its long axis.

VISUAL DIFFERENCES

Catch quality:

- High values keep the elbow higher.
- High values make the forearm more vertical.
- Low values drop the elbow.

Slip:

- High values move the underwater hand backwards towards the feet.
- High values slightly fold the wrist.
- High values reduce distance per stroke.

Drive balance:

- Low values make the stroke look more arm-driven.
- High values increase hip and shoulder timing connection.
- High values must not add free speed if catch quality is poor.

MUSCLE VISUALISATION

Use simple coloured patches or limb/torso highlights.

Do not create anatomically exact muscles.

Back emphasis:

- Highlight the side and rear torso during catch and pull.

Triceps emphasis:

- Highlight the back of the upper arm during the finish.

Hips/core emphasis:

- Highlight the waist, oblique, and hip region during body rotation.

Balanced:

- Display softer contributions across all three regions.

Label the visual:

“Estimated contribution for this modelled stroke”

Do not call it EMG, measured activation, strength, or medical data.

PRESETS

Long power:

- catch 92%
- roll 46 degrees
- rate 38
- slip 8%
- drive 85%
- long visible underwater path

Long light:

- catch 88%
- roll 44 degrees
- rate 40
- slip 10%
- drive 70%
- lower muscle-highlight intensity than Long power

Compact connected:

- catch 82%
- roll 42 degrees
- rate 48
- slip 14%
- drive 68%
- shorter underwater path and earlier exit

Short slipping:

- catch 42%
- roll 34 degrees
- rate 54
- slip 62%
- drive 35%
- visibly poor distance per stroke

SIMPLE ESTIMATES

Use these coaching estimates:

hold_quality =
    0.6 * catch_quality
    + 0.4 * (1 - slip)

connection =
    0.7 + 0.3 * drive_balance

rate_penalty =
    max(0, stroke_rate - 56) / 80

distance_per_stroke =
    clamp(
        0.55
        + 0.75 * hold_quality * connection
        - 0.40 * slip
        - rate_penalty,
        0.45,
        1.40,
    )

strokes_per_25 = 25 / distance_per_stroke

seconds_per_25 = strokes_per_25 * 60 / stroke_rate

All values must be labelled estimated.

VISUAL STYLE

Use:

- background #08141a;
- panels #123038;
- text #e7f0ea;
- holding #3dbea5;
- slipping #e36b4f.

The swimmer is the primary object.

Keep all copy short.

DO NOT BUILD YET

Do not build:

- a Count page;
- persistence;
- history;
- a side-view SVG;
- a skeleton overlay;
- particles;
- a ghost arm;
- direct elbow dragging;
- detailed breathing options;
- detailed muscle anatomy;
- browser automation;
- an extensive test suite;
- a complex project structure.

DELIVERABLE

Produce a working prototype that starts with:

python main.py

Before stopping:

1. Run the application.
2. Fix Python startup errors.
3. Confirm all four presets change the swimmer and estimates.
4. Confirm Play/Pause works.
5. Confirm the app contains no sound or microphone features.

Do not spend time on production architecture or visual perfection.
