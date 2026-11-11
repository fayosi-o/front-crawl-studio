# Long Catch prototype instructions

This is a 30–60 minute visual prototype built with Python 3.12 and NiceGUI.
The full specification is `docs/BUILD_SPEC.md`.

Keep the implementation in one `main.py` file until it works.

## Rules

- Run locally at 127.0.0.1:8080.
- Use NiceGUI and `ui.scene`.
- Do not use Node.js, npm, React, databases, cloud services, or CDNs.
- Do not add audio, voice, speech, microphone access, AudioContext,
  media files, mute controls, or volume controls.
- Create a simple procedural human, not a stick figure and not a realistic model.
- Build with basic cylinders, spheres, groups, and flattened hands and feet.
- Count every hand entry as one stroke.
- A complete right-and-left cycle contains two strokes.
- Cycle duration is `120 / stroke_rate`.
- More slip must reduce distance per stroke.
- More force or drive must not rescue a poor catch.
- Muscle colours are estimated visual contributions, not EMG or medical data.
- Prefer a visibly working prototype over architecture or polish.
- Do not add unrequested pages, modules, services, tests, or features.
- Run the application before claiming success.
