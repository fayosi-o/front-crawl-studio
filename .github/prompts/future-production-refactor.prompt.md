---
agent: agent
description: DEFERRED. Typed models, phase maths, timing, formatting, pytest, and Ruff. Only after the visual prototype passes its checklist and only on explicit request.
---

> **Deferred.** This belongs to a possible future production refactor. It is
> not part of the initial build. Do not run it unless the user explicitly asks,
> after `main.py` passes the BUILD_SPEC.md section 15 checklist.

Read these files completely before editing:

- BUILD_SPEC.md
- main.py
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
