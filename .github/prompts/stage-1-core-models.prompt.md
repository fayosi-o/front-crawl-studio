---
agent: agent
description: Stage 1 only - typed models, stroke phases, cycle timing, formatting, and pytest tests. No UI.
---

Read these files completely before editing:

- docs/BUILD_SPEC.md
- .github/copilot-instructions.md
- AGENTS.md

We are implementing Stage 1 only:

- typed settings and state models;
- stroke phase definitions;
- phase-to-step mapping;
- left/right arm phase calculation;
- cycle-duration calculation;
- duration formatting;
- associated pytest tests.

Do not implement NiceGUI, SVG, Three.js, browser JavaScript, propulsion,
muscle overlays, persistence, or visual polish yet.

First inspect the repository and give me:

1. the files you will create or change;
2. the public APIs you propose;
3. the boundary cases the tests will cover;
4. any conflict you found in BUILD_SPEC.md.

Then implement the stage, run the focused tests, run Ruff, and report:

- files changed;
- commands executed;
- test result;
- any remaining issue.

Do not claim success without command output.
