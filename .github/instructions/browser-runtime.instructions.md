---
applyTo: "long_catch/static/js/**"
---

# Browser runtime instructions

- Use plain local JavaScript without npm or an external build process.
- Do not use external scripts, CDNs, audio APIs, microphone APIs,
  media elements, cookies, or network requests.
- Use requestAnimationFrame for model animation.
- Pause animation work while `document.hidden` is true.
- Reuse scene, SVG, particle, vector, and material objects.
- Do not send frame-by-frame phase updates to Python.
- Throttle continuous server-bound drag events.
- Keep all query selectors scoped to the Long Catch root.
- Prevent duplicate event listeners after NiceGUI reconnects.
