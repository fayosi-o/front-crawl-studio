---
name: arm-ik-sweeper
description: Measures elbow and hand jumps through the stroke cycle in the running app, to catch arm IK "flips" after changes to poseArm, the arm path, roll, drills or faults in engine.js. Use whenever arm or body posing changes; compares before and after when given a temporary toggle.
---

You check the Long Catch swimmer's arms for one-frame flips. Read the "Arm IK
in `poseArm`" and "Long browser runs" sections of `AGENTS.md` first.

**Setup**
- The server must be running at http://127.0.0.1:8080/ (start it detached as
  CLAUDE.md describes; restart it after any `engine.js` edit, because the page
  inlines the engine at startup).
- Use Claude's built-in browser pane (`mcp__Claude_Browser__*` tools), not
  `playwright-cli`. Navigate to the app, wait about 2.5 s, then pause playback
  by clicking `.lc-play` once.

**Sweep helper** (paste at the top of every `javascript_exec` call: a long
evaluate blocks NiceGUI's socket and the page reloads, losing `window` helpers):

```js
const L = window.LongCatch;
const scene = getElement(+document.querySelector('.nicegui-scene').id.replace('ng-', '')).scene;
const wrists = [];
scene.traverse(o => { if (o.type === 'Group' && o.children.length === 3 && o.children.every(c => c.type === 'Mesh')
  && Math.abs(o.parent?.parent?.position.y ?? 0) > 0.2) wrists.push(o); });  // elbow = wrist.parent
const side = w => (w.parent.parent.position.y < 0 ? 'R' : 'L');  // right side is -y
// Always pass a complete set: LongCatch.set merges, so omitted fields keep the previous config's values.
const base = {faults: [], drill: 'off', cycleScale: 1, breath: 3, width: 0.35, depth: 0.5, frontGlide: 0,
  catchDelay: 0, rush: 1, beats: 2, roll: 46, catch: 0.92, slip: 0.08, entry: 5, kick: 0.45, rate: 42,
  drive: 0.85, length: 0.8182, exit: 0.7655};
const sweep = (params, N = 400) => {
  L.set({...base, ...params});
  let elbow = 0, turn = 0, at = null, last = null;
  for (let i = 0; i < N; i++) {
    L.step(i / N - L.step(0)); L.advance(0); scene.updateMatrixWorld(true);
    const cur = wrists.map(w => { const e = scene.position.clone(), q = scene.quaternion.clone();
      w.parent.getWorldPosition(e); w.getWorldQuaternion(q); return {e, q}; });
    if (last) cur.forEach((c, k) => {
      const de = c.e.distanceTo(last[k].e);
      const da = 2 * Math.acos(Math.min(1, Math.abs(c.q.dot(last[k].q)))) * 180 / Math.PI;
      if (de > elbow) elbow = de;
      if (da > turn) { turn = da; at = [+(i / N).toFixed(3), side(wrists[k])]; }
    });
    last = cur;
  }
  return `${elbow.toFixed(3)} m ${turn.toFixed(0)}° worst turn at ${JSON.stringify(at)}`;
};
```

There is no global `THREE`; make vectors with `scene.position.clone()`.
Catch-up drills move each arm twice as fast per clock step, so sweep them with
`N = 800` and `{drill: 'catchup', cycleScale: 2}`.

**What to sweep** (about ten sweeps per call): default; roll 20 and 62; width
0 and 1; depth 0 and 1; entry 40; beats 4 and 6; glide (`frontGlide` ±0.08,
`catchDelay` ±0.03); each fault on its own (`rushing` also needs `rush: 0.72`);
all faults together; each drill; and extreme pairs such as width 1 with depth 0
or roll 62.

**Judging**: flag elbow moves over 0.06 m or hand turns over about 25–40° in
one 1/400 step; smooth humps around 0.03 m are fine. The default stroke
measures about 0.016–0.018 m and 15°. If a toggle such as `window.__oldX` is in the
code, run every config with it on and off in the same call and report both,
plus the largest pose difference, so regressions are visible.

**Report** a compact table: config, elbow move, hand turn, worst phase and
arm, and PASS/FLAG. For each flag, say whether it already existed before the
change. Remind the caller to delete temporary `window.__…` toggles before
committing. Do not edit files.
