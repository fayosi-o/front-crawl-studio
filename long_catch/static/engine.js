// Long Catch browser animation engine.
//
// Python owns the settings and sends them through window.LongCatch.set();
// this loop owns the live cycle phase and poses the swimmer every frame.
// Configuration arrives as window.LONG_CATCH_CONFIG (colours, phase boundaries, arm lengths).
// Coordinates: head towards +x, z up, right side towards -y, water surface at z = 0.
window.createLongCatchEngine = function ({root = '.lc-studio', externalClock = false} = {}) {
  const CONFIG = window.LONG_CATCH_CONFIG;
  // Engine state. `el`, `m`, `home`, `view`, and `puff` are filled in lazily.
  const S = {
    sceneId: null, ids: null,   // scene element id and named object ids from Python
    params: null, faults: {},   // latest render params; active faults as {key: true}
    phase: 0,                   // right-arm cycle phase in [0, 1)
    cycles: 0,                  // whole cycles played; seeds the natural variation and breathing pattern
    offset: 0,                  // distance swum, used to scroll the lane ropes and pool floor
    last: null,                 // previous frame timestamp (null after a pause or seek)
    m: null,                    // resolved meshes and per-arm IK scratch objects
    running: false,             // animation loop and listeners installed
    ui: {},                     // cached DOM nodes and last-written values
    trails: {}, trailReset: false,
    active: true, ride: null, seekPausePending: false,
  };

  // ---- maths helpers --------------------------------------------------------
  const D = Math.PI / 180;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = t => t * t * (3 - 2 * t);
  const wrap = p => ((p % 1) + 1) % 1;
  const bump = (p, a, b) => (p > a && p < b ? Math.sin(Math.PI * (p - a) / (b - a)) : 0);  // 0→1→0 over (a, b)
  const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);  // '#rrggbb' → [r, g, b] in 0–1
  // Smooth value noise in [-1, 1]: one random value per whole t, eased between neighbours.
  const hash = (i, seed) => { const v = Math.sin(i * 127.1 + seed * 311.7) * 43758.5453; return 2 * (v - Math.floor(v)) - 1; };
  const noise = (t, seed) => { const i = Math.floor(t); return lerp(hash(i, seed), hash(i + 1, seed), smooth(t - i)); };
  const C = { hold: rgb(CONFIG.colors.hold), slip: rgb(CONFIG.colors.slip), skin: rgb(CONFIG.colors.skin) };
  const EMPHASIS = { back: [1, 0, 0], triceps: [0, 1, 0], core: [0, 0, 1], balanced: [0.55, 0.55, 0.55] };
  const PHASES = CONFIG.phases;
  const [UPPER, FOREARM] = CONFIG.arm;
  // Shoulder-to-wrist distance for an elbow bent by `bend` degrees; reach is limited to 8–145°.
  const reachAt = bend => Math.sqrt(UPPER ** 2 + FOREARM ** 2 + 2 * UPPER * FOREARM * Math.cos(bend * D));
  const MIN_REACH = reachAt(145);
  const MAX_REACH = reachAt(8);
  // Fraction of the cycle at which the right shoulder is deepest (the right catch).
  const ROLL_PEAK = 0.18;
  // Ease into the reach limits (metres) so the elbow straightens or folds gradually instead of snapping.
  const SOFT = 0.045;
  function softReach(d, min = MIN_REACH) {
    if (d > MAX_REACH - SOFT) return MAX_REACH - SOFT * Math.exp(-(d - MAX_REACH + SOFT) / SOFT);
    if (d < min + SOFT) return min + SOFT * Math.exp(-(min + SOFT - d) / SOFT);
    return d;
  }
  // Under water the elbow never folds past about 95 degrees of bend: the power diamond keeps the
  // hand a forearm's length below the elbow rather than tucked into the armpit.
  const PULL_REACH = reachAt(95);

  // Smoothly interpolate a keyframe list [[phase, value], ...] at phase p.
  function keyed(p, keys) {
    for (let i = 0; i < keys.length - 1; i++) {
      const [p0, v0] = keys[i], [p1, v1] = keys[i + 1];
      if (p <= p1) return lerp(v0, v1, smooth(clamp((p - p0) / (p1 - p0), 0, 1)));
    }
    return keys[keys.length - 1][1];
  }

  // ---- arm path ---------------------------------------------------------------

  // Wrist target path for one arm at phase p, plus overlay and colouring values.
  // F holds active stroke faults; each one bends the healthy path toward a typical error.
  // Path coordinates are forward reach, lane-relative outward offset, and water-relative height.
  // `out` is measured from the rolled shoulder's lane position; elbow and palm guides are body-relative.
  function arm(p, P, F) {
    const c = P.catch, s = P.slip, L = P.length, w = P.width ?? 0.35;
    const exit = P.exit, fin = CONFIG.finish, pull = CONFIG.pull, push = CONFIG.push;
    // Stroke depth: -1 keeps the hand tucked close to the body, +1 pulls deep with a straighter arm.
    const d = 2 * P.depth - 1;
    const rec = f => exit + (1 - exit) * f;  // fraction f of the way through the recovery
    const midRec = rec(0.4), lateRec = rec(0.7), preEntry = rec(0.88);
    const over = F.overreach ? 1 : 0, cross = F.crossover ? 1 : 0;
    // Entry angle tilts the extended arm about the shoulder: 0 deg skims the surface, larger points to the floor.
    const tilt = deg => [0.56 * Math.cos(deg * D), -0.56 * Math.sin(deg * D)];
    const [enterX, enterH] = tilt(P.entry), [glideX, glideH] = tilt(P.entry + 3);
    // Fingertips go in just past the head with the elbow still bent and high, then the arm extends
    // forward under the surface. An over-reaching swimmer spears in at full stretch instead.
    const entryX = lerp(0.36, enterX + 0.08, over), entryH = lerp(-0.01, enterH + 0.03, over);
    const pullX = lerp(0.10, 0.27, c) - 0.12 * s + 0.10 * over;
    const finishX = -lerp(0.40, 0.50, L), exitX = -lerp(0.42, 0.52, L);
    let x = keyed(p, [
      [0, entryX], [0.11, enterX + 0.08 * over], [0.16, glideX - 0.01 + 0.08 * over],
      [0.22, lerp(0.30, 0.40, c) + 0.08 * over],
      [pull, pullX], [fin, finishX], [exit, exitX],
      [midRec, -0.10], [lateRec, 0.16], [preEntry, 0.30], [1, entryX],
    ]);
    // One uninterrupted sweep: pull under the chest, then extend back toward the hip.
    // The slight timing bias puts peak rearward hand speed in the push, not at a stop under the shoulder.
    if (p >= pull && p < fin) x = lerp(pullX, finishX, smooth(((p - pull) / (fin - pull)) ** 1.25));
    // Pull width: a narrow pull sweeps the hand in under the chest while the elbow stays out (the
    // "power diamond" of the hand, forearm, and upper arm); a wide one keeps the hand outside the
    // shoulder line with a straighter arm. Both open slightly out at the catch first.
    // A crossover hand enters past the head's centre line, then sweeps back out during the pull.
    const out = keyed(p, [
      [0, 0.02], [0.11, 0.03], [0.16, 0.04], [0.22, 0.05 + 0.05 * w + 0.03 * (1 - c)],
      [0.36, lerp(-0.15, 0.12, w)], [push, lerp(-0.13, 0.11, w)],
      [fin, lerp(-0.06, 0.09, w)], [exit, lerp(0.0, 0.10, w)],
      [midRec, 0.20], [lateRec, 0.16], [preEntry, 0.06], [1, 0.02],
    ]) - cross * keyed(p, [
      [0, 0.33], [0.16, 0.31], [0.30, 0.15], [push, 0.02], [exit, 0], [lateRec, 0.08], [preEntry, 0.24], [1, 0.33],
    ]);
    // Distance-style catch: the hand tips down in front while the elbow stays high, then hangs
    // under the elbow so the forearm and hand form one near-vertical paddle facing backwards.
    const height = keyed(p, [
      [0, entryH], [0.11, enterH + 0.03 * over], [0.16, glideH + 0.05 * over],
      [0.22, lerp(-0.16, -0.22, c) + 0.03 * over],
      [0.30, lerp(-0.26, -0.40, c) - 0.05 * d],
      [push, -0.32 - 0.08 * d], [fin, -0.06 - 0.02 * d], [exit, 0.0],
      [midRec, 0.10], [lateRec, 0.10], [preEntry, 0.06], [1, entryH],
    ]);
    // Recovery is elbow-led and compact: the elbow lifts highest while the relaxed forearm hangs
    // beneath it, close to the body, then swings forward past the head to the entry.
    const elbow = [
      keyed(p, [[exit, -0.24], [midRec, -0.04], [lateRec, 0.10], [preEntry, 0.14], [1, 0.16]]),
      keyed(p, [[exit, 0.12], [midRec, 0.18], [lateRec, 0.18], [preEntry, 0.14], [1, 0.10]]),
      keyed(p, [[exit, 0.16], [midRec, 0.30], [lateRec, 0.26], [preEntry, 0.18], [1, 0.10]]),
    ];
    const recovery = p < exit ? 0 : smooth(clamp((p - exit) / 0.05, 0, 1)) * smooth(clamp((1 - p) / 0.07, 0, 1));
    const under = p < exit;
    // Underwater elbow direction. The upper arm rotates inward through the catch so the elbow
    // points out and up and stays ahead of the hand; a weak catch lets it drop and trail.
    // Narrow pulls flare the elbow out to the side; wide pulls point it back and up. Through the
    // push the guide stays mostly outward: with the body rolled onto the pulling side, world-up
    // points under the chest, so a large up share would fold the elbow inward.
    const dropped = lerp(-0.6, 0.35, c);
    const elbowDir = [0, 1, 2].map(i => keyed(p, [
      [0, [0.15, 0.75, 0.65][i]], [0.12, [0.15, 0.75, 0.65][i]],
      [0.22, [lerp(-0.1, 0.35, c), 0.8, dropped][i]],
      [0.36, [lerp(0.15, -0.2, w), 1.0, lerp(0.1, 0.45, w)][i]],
      [push, [0.0, 0.95, 0.25][i]], [fin, [-0.3, 0.6, 0.7][i]], [1, [0.15, 0.75, 0.65][i]],
    ]));
    // Palm direction for the forearm twist. Down and slightly out at entry, back through the catch
    // and push, pinkie-first and facing the thigh at release, then facing back and out (thumb down)
    // as the elbow lifts, and out to the side as the hand swings forward to the entry. Slip skews the palm inward so it slices rather than holds.
    const palm = [0, 1, 2].map(i => keyed(p, [
      [0, [0.1, 0.3, -1][i]], [0.14, [0.1, 0.15, -1][i]], [0.22, [-0.7, 0, -0.7][i]],
      [0.36, [-1, -0.25 * (1 - w), -0.15][i]], [push, [-1, 0, 0.35][i]],
      [fin, [-0.2, -0.8, 0.5][i]], [exit, [-0.2, -0.6, 0.6][i]],
      [midRec, [-0.6, 0.6, 0.2][i]], [lateRec, [-0.2, 1, -0.1][i]],
      [preEntry, [0, 0.45, -1][i]], [1, [0.1, 0.3, -1][i]],
    ]));
    palm[1] -= 0.9 * s * bump(p, 0.14, fin);
    // Over-extension: locked arm, shrugged shoulder, and a "stop sign" wrist that brakes at the front.
    const front = over * keyed(p, [[0, 1], [0.16, 1], [0.30, 0], [0.92, 0], [1, 1]]);
    const wrist = (under ? -48 * s * bump(p, 0.08, exit) + 12 * (1 - s) * bump(p, 0.12, 0.45) : 15) - 32 * front;
    const stage = p < 0.12 ? 0 : p < pull ? 1 : p < push ? 2 : p < fin ? 3 : p < exit ? 4 : 5;
    return {
      x, out, height, elbow, recovery, elbowDir, palm, shrug: front,
      wrist: wrist * D, under, stage,
      back: bump(p, 0.10, fin + 0.02), triceps: bump(p, push, exit),
    };
  }

  // Smooth front-end timing adjustment; the pull and recovery keep their original clock phases.
  function strokePhase(p, P) {
    return p < CONFIG.pull ? p - P.frontGlide * Math.sin(Math.PI * p / CONFIG.pull) ** 2 : p;
  }

  // Spinning arms race through the underwater part, leaving more of the cycle for recovery.
  function rushed(p, P) {
    if (P.rush >= 1) return p;
    const exit = P.exit, early = exit * P.rush;
    return p < early ? p * exit / early : exit + (p - early) * (1 - exit) / (1 - early);
  }

  // ---- natural motion ---------------------------------------------------------
  // Visual only: these never touch the phase, the timeline, or the Python metrics.
  // Variation is keyed to stroke time (cycles + phase), so it holds still while paused.

  // Bilateral breathing every third stroke (one breath per 1.5 cycles, alternating sides). The head
  // turns toward the arm as it finishes and starts its recovery, then rotates back down by the end
  // of the recovery, before that hand enters again.
  // Returns -1..1: negative turns the face to the right (-y), positive to the left.
  function breathing(P) {
    const t = S.cycles + S.phase, exit = P.exit;
    const turnWindow = p => keyed(p, [[exit - 0.22, 0], [exit - 0.04, 1], [exit + 0.08, 1], [exit + 0.2, 0]]);
    const breathes = n => ((n % 3) + 3) % 3 === 0;  // n counts hand entries: right even, left odd
    const right = breathes(2 * Math.floor(t)) ? turnWindow(S.phase) : 0;
    const left = breathes(2 * Math.floor(t - 0.5) + 1) ? turnWindow((S.phase + 0.5) % 1) : 0;
    return left - right;
  }

  // No two strokes are identical: nudge the wrist target by a centimetre or so, drifting smoothly.
  function vary(a, t, seed) {
    const k = 0.014;
    a.x += k * noise(t, seed);
    a.out += k * noise(t, seed + 1);
    a.height += k * noise(t, seed + 2);
  }

  // ---- scene setup and cameras ------------------------------------------------

  // Look up the scene meshes once they exist; returns false until NiceGUI has created them all.
  function resolve() {
    if (S.m) return true;
    const el = typeof getElement === 'function' ? getElement(S.sceneId) : null;
    if (!el || !el.objects) return false;
    const m = {};
    for (const [name, id] of Object.entries(S.ids)) {
      if (Array.isArray(id)) {
        m[name] = id.map(i => el.objects.get(i)?.mesh);
        if (m[name].some(x => !x)) return false;
      } else {
        m[name] = el.objects.get(id)?.mesh;
        if (!m[name]) return false;
      }
    }
    m.water.material.depthWrite = false;
    // Emphasis patches are an x-ray overlay so limbs and torso never hide them.
    for (const k of ['backR', 'backL', 'triR', 'triL', 'core', 'hipR', 'hipL']) {
      Object.assign(m[k].material, { depthWrite: false, depthTest: false });
      m[k].renderOrder = 10;
    }
    m.basePos = m.buoys.map(b => b.position.x);
    // Roll about the body axis first, then yaw it (snaking) in the water plane.
    m.chest.rotation.order = 'ZYX';
    m.pelvis.rotation.order = 'ZYX';
    m.rigs = {};
    m.motion = null;
    m.bodyOrigin = m.chest.parent.position.clone();
    m.probes = PRESSURE.probes.map(p => ({
      ...p, pos: m.chest.position.clone(), prev: m.chest.position.clone(),
      velocity: m.chest.position.clone(), normal: m.chest.position.clone(),
      axis: m.chest.position.clone(), known: false,
    }));
    for (const side of ['R', 'L']) {
      const shoulder = m['sh' + side], vector = () => shoulder.position.clone();
      m.rigs[side] = {
        target: vector(), axis: vector(), pole: vector(), hint: vector(), elbow: vector(),
        upper: vector(), lower: vector(), normal: vector(), z: vector(),
        matrix: shoulder.matrix.clone(), quaternion: shoulder.quaternion.clone(), baseX: shoulder.position.x,
      };
    }
    el.$el.style.width = '100%';
    el.$el.style.height = '100%';
    S.el = el;
    S.m = m;
    S.home = el.camera ? { position: el.camera.position.clone(), target: el.controls.target.clone() } : null;
    setTimeout(fitCamera, 50);
    return true;
  }

  // Keep the whole swimmer in view whatever the canvas aspect ratio.
  function fitCamera() {
    const el = S.el;
    if (!el || !el.camera || !el.controls) return;
    const cam = el.camera, target = el.controls.target;
    const width = el.$el.clientWidth, height = el.$el.clientHeight;
    if (!width || !height) return;
    const aspect = width / height;
    const needed = 1.45 / (Math.tan(cam.fov * D / 2) * aspect);
    const dir = cam.position.clone().sub(target).normalize();
    cam.position.copy(target).addScaledVector(dir, Math.max(2.3, needed));
    el.controls.update();
  }

  // Return the main camera to where it started, then refit it.
  function resetCamera() {
    if (!S.el || !S.home) return;
    S.el.camera.position.copy(S.home.position);
    S.el.controls.target.copy(S.home.target);
    fitCamera();
  }

  // ---- ghost trails -----------------------------------------------------------

  // Ghost trails: fading smoke behind the fingertips and toes that drifts back with the water.
  // THREE comes from NiceGUI's own scene module via the page import map (no CDN).
  let THREE = null;
  import('nicegui-scene').then(mod => { THREE = mod.THREE; }).catch(error => {
    console.error('Long Catch could not load its scene effects.', error);
  });
  const MAX_TRAIL = 360;  // samples per trail (~6 s at 60 fps)
  const TRAIL_LIMBS = {
    hands: ['R', 'L'].map(s => ({ key: 'hand' + s, joint: 'wr' + s, tip: [0.13, 0, 0], color: C.hold })),
    feet: ['R', 'L'].map(s => ({ key: 'foot' + s, joint: 'ankle' + s, tip: [-0.15, 0, -0.01], color: rgb('#a9d4ff') })),
  };
  TRAIL_LIMBS.both = [...TRAIL_LIMBS.hands, ...TRAIL_LIMBS.feet];
  const ALL_LIMBS = TRAIL_LIMBS.both;

  // Soft round sprite shared by every trail's points.
  function puffTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 64;
    const g = canvas.getContext('2d'), grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.4, 'rgba(255,255,255,0.45)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(canvas);
  }

  // One trail = fixed-size buffers drawn twice: soft points (smoke) and a thin line (path).
  function makeTrail(limb) {
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(MAX_TRAIL * 3), col = new Float32Array(MAX_TRAIL * 4);
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 4).setUsage(THREE.DynamicDrawUsage));
    geo.setDrawRange(0, 0);
    const common = { vertexColors: true, transparent: true, depthWrite: false };
    S.puff = S.puff || puffTexture();
    const points = new THREE.Points(geo, new THREE.PointsMaterial({ ...common, size: 0.09, map: S.puff }));
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial(common));
    for (const obj of [points, line]) { obj.frustumCulled = false; obj.renderOrder = 5; }
    S.el.scene.add(points, line);
    return { limb, pts: [], geo, pos, col, points, line, at: new THREE.Vector3() };
  }

  // Age, drift, and append trail samples; trails are created on first use and hidden when off.
  // Each sample is [x, y, z, age in seconds].
  function updateTrails(m, P, dt) {
    if (!THREE) return;
    const wanted = TRAIL_LIMBS[P.trail] || [], seconds = P.trailSeconds || 1.5;
    for (const limb of ALL_LIMBS) {
      let t = S.trails[limb.key];
      const on = wanted.includes(limb);
      if (!on && !t) continue;
      if (!t) t = S.trails[limb.key] = makeTrail(limb);
      if (!on || S.trailReset) t.pts.length = 0;
      t.points.visible = t.line.visible = on;
      if (!on) continue;
      if (dt > 0) {
        const drift = (S.flow ?? P.speed) * dt;
        for (const q of t.pts) { q[0] -= drift; q[3] += dt; }
        m[limb.joint].localToWorld(t.at.set(...limb.tip));
        t.pts.push([t.at.x, t.at.y, t.at.z, 0]);
      }
      while (t.pts.length && (t.pts[0][3] > seconds || t.pts.length > MAX_TRAIL)) t.pts.shift();
      const n = t.pts.length, [r, g, b] = limb.color;
      for (let i = 0; i < n; i++) {
        const q = t.pts[i], fade = Math.max(0, 1 - q[3] / seconds) ** 1.4;
        t.pos[3 * i] = q[0]; t.pos[3 * i + 1] = q[1]; t.pos[3 * i + 2] = q[2];
        t.col[4 * i] = r; t.col[4 * i + 1] = g; t.col[4 * i + 2] = b; t.col[4 * i + 3] = 0.85 * fade;
      }
      t.geo.attributes.position.needsUpdate = true;
      t.geo.attributes.color.needsUpdate = true;
      t.geo.setDrawRange(0, n);
    }
    S.trailReset = false;
  }

  // ---- water and lighting -----------------------------------------------------

  // Surface: a fine grid with a gentle travelling swell, a small bow wave at the head, and a soft sheen.
  // Floor: tiles and two layers of drifting caustics, well below the swimmer.
  // Every layer fades out at its edges so the pool has no hard slab outline.
  const SURFACE = { w: 10, h: 4, nx: 120, ny: 48, x: -0.5 };
  const SWELL = [[2.1, 1.3, 1.7, 0.018], [3.4, -2.2, 2.6, 0.012], [7.9, 5.1, 4.1, 0.005]];
  // Fine ripples: one tile of the ripple normal map covers RIPPLE_TILE metres; a second, smaller
  // sample of the same map drifts the other way so the pattern never visibly repeats.
  const RIPPLE_TILE = 0.7;
  const FLOOR_Z = -2.1;

  function canvasTexture(size, draw, repeat) {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    draw(canvas.getContext('2d'), size);
    const tex = new THREE.CanvasTexture(canvas);
    if (repeat) { tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(...repeat); }
    return tex;
  }

  // White in the middle, fading to black at every edge (used as an alpha map).
  function drawEdgeFade(g, n, band = 0.22) {
    g.fillStyle = '#fff';
    g.fillRect(0, 0, n, n);
    g.globalCompositeOperation = 'multiply';
    for (const [x1, y1] of [[n, 0], [0, n]]) {
      const grad = g.createLinearGradient(0, 0, x1, y1);
      grad.addColorStop(0, '#000');
      grad.addColorStop(band, '#fff');
      grad.addColorStop(1 - band, '#fff');
      grad.addColorStop(1, '#000');
      g.fillStyle = grad;
      g.fillRect(0, 0, n, n);
    }
  }

  // Fine, broken streaks that reveal the water sliding past the swimmer.
  function drawFlow(g, n) {
    g.fillStyle = '#fff';
    g.fillRect(0, 0, n, n);
    for (let i = 0; i < 38; i++) {
      const base = (i * 67.7) % n, phase = i * 1.91;
      g.beginPath();
      for (let x = 0; x <= n; x += 8) {
        const u = x / n * Math.PI * 2;
        const y = base + 2.2 * Math.sin(u + phase) + 0.8 * Math.sin(3 * u - phase);
        if (x === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
      const alpha = 0.08 + 0.12 * ((i * 17) % 7) / 6;
      g.strokeStyle = `rgba(177, 231, 241, ${alpha})`;
      g.lineWidth = i % 9 === 0 ? 2 : 1;
      g.stroke();
    }
  }

  // One metre of floor: 4 × 4 tiles with slight shade variation and pale grout.
  function drawTiles(g, n) {
    const base = rgb(CONFIG.colors.floor).map(v => v * 255), tile = n / 4;
    for (let i = 0; i < 4; i++) {
      for (let j = 0; j < 4; j++) {
        const k = 0.94 + 0.12 * (((i * 7 + j * 13) % 5) / 4);
        g.fillStyle = `rgb(${base.map(v => Math.round(v * k)).join(',')})`;
        g.fillRect(i * tile, j * tile, tile, tile);
      }
    }
    g.strokeStyle = 'rgba(160, 215, 225, 0.12)';
    g.lineWidth = 2;
    for (let i = 0; i <= 4; i++) {
      g.beginPath(); g.moveTo(i * tile, 0); g.lineTo(i * tile, n); g.stroke();
      g.beginPath(); g.moveTo(0, i * tile); g.lineTo(n, i * tile); g.stroke();
    }
  }

  // Tileable caustic web: bright where two cellular-noise cells meet (Worley F2 − F1 near zero).
  function drawCaustics(g, n) {
    const seeds = Array.from({ length: 14 }, (_, i) => [((i * 0.618) % 1) * n, ((i * 0.377 + 0.13 * (i % 3)) % 1) * n]);
    const img = g.createImageData(n, n);
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        let f1 = Infinity, f2 = Infinity;
        for (const [sx, sy] of seeds) {
          const dx = Math.min(Math.abs(x - sx), n - Math.abs(x - sx)), dy = Math.min(Math.abs(y - sy), n - Math.abs(y - sy));
          const d = Math.hypot(dx, dy);
          if (d < f1) { f2 = f1; f1 = d; } else if (d < f2) f2 = d;
        }
        const v = Math.max(0, 1 - (f2 - f1) / (0.07 * n)) ** 2.2, o = 4 * (y * n + x);
        img.data[o] = img.data[o + 1] = img.data[o + 2] = 255 * v;
        img.data[o + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  }

  // Tileable ripple normal map: a sum of short waves with whole-number frequencies (so it wraps
  // seamlessly), encoded as a tangent-space normal map. Generated once.
  function drawRipples(g, n) {
    const waves = [[3, 1, 0.0], [-2, 4, 1.3], [5, -3, 2.1], [1, 7, 0.7], [-7, 2, 4.2], [9, 5, 2.9], [-4, -9, 5.5]]
      .map(([kx, ky, phase]) => [2 * Math.PI * kx, 2 * Math.PI * ky, phase, 1 / Math.hypot(kx, ky)]);
    const img = g.createImageData(n, n);
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        let dx = 0, dy = 0;
        for (const [kx, ky, phase, amp] of waves) {
          const c = amp * Math.cos(kx * x / n + ky * y / n + phase);
          dx += kx * c; dy += ky * c;
        }
        const sx = -0.012 * dx, sy = -0.012 * dy, len = Math.hypot(sx, sy, 1), o = 4 * (y * n + x);
        img.data[o] = 127.5 * (sx / len + 1);
        img.data[o + 1] = 127.5 * (sy / len + 1);
        img.data[o + 2] = 127.5 * (1 / len + 1);
        img.data[o + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  }

  // Blend a second, smaller sample of the ripple map that drifts on its own (uniform lcRipple).
  // Also adds a cheap Fresnel term: looking across the surface at a low angle, water reflects more
  // sky, so it turns more opaque and lighter; looking straight down it stays clear.
  function addSecondRipple(material, uniform) {
    material.onBeforeCompile = shader => {
      const line = 'vec3 mapN = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;';
      const maps = '#include <normal_fragment_maps>', out = '#include <opaque_fragment>';
      const chunk = THREE.ShaderChunk.normal_fragment_maps || '';
      if (!chunk.includes(line) || !shader.fragmentShader.includes(maps) || !shader.fragmentShader.includes(out)) return;
      shader.uniforms.lcRipple = uniform;
      shader.fragmentShader = 'uniform vec3 lcRipple;\n' + shader.fragmentShader.replace(maps, chunk.replace(line, `
        vec3 rippleA = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;
        vec3 rippleB = texture2D( normalMap, vNormalMapUv * lcRipple.z + lcRipple.xy ).xyz * 2.0 - 1.0;
        vec3 mapN = normalize( vec3( rippleA.xy + rippleB.xy, rippleA.z * rippleB.z ) );`)).replace(out, `
        float lcFresnel = pow( 1.0 - clamp( abs( dot( normal, normalize( vViewPosition ) ) ), 0.0, 1.0 ), 3.0 );
        outgoingLight = mix( outgoingLight, vec3( 0.36, 0.62, 0.70 ), lcFresnel * 0.4 );
        diffuseColor.a = min( diffuseColor.a * ( 1.0 + lcFresnel * 2.2 ), 0.6 );
        ${out}`);
    };
  }

  // Replace NiceGUI's flat default lights (strong ambient + one overhead light) with a higher-contrast rig.
  // White light keeps the palette colours strong; less ambient and a stronger key light from above-front
  // add shading, and a faint cool rim light from behind separates the swimmer from the dark water.
  // No shadows, so rendering cost is unchanged.
  function setupLighting(group) {
    for (const light of S.el.scene.children.filter(o => o.isAmbientLight || o.isDirectionalLight)) {
      S.el.scene.remove(light);
    }
    const key = new THREE.DirectionalLight(0xffffff, 1.9);
    key.position.set(3, -2.5, 6);
    const rim = new THREE.DirectionalLight(0x9fe4ff, 0.5);
    rim.position.set(-4, 3, -1.5);
    group.add(new THREE.AmbientLight(0xffffff, 1.5), key, rim);
  }

  // Build the surface waves, pool floor, and lights once per scene; returns false until THREE has loaded.
  function setupWater(m) {
    if (m.pool) return true;
    if (!THREE) return false;
    const scene = S.el.scene, edge = canvasTexture(128, drawEdgeFade);
    const flow = canvasTexture(256, drawFlow, [4, 2]);
    const ripple = canvasTexture(256, drawRipples, [SURFACE.w / RIPPLE_TILE, SURFACE.h / RIPPLE_TILE]);
    const rippleB = { value: new THREE.Vector3(0, 0, 1.73) };
    const old = scene.getObjectByName('lc-pool');
    if (old) scene.remove(old);

    m.water.geometry.dispose();
    m.water.geometry = new THREE.PlaneGeometry(SURFACE.w, SURFACE.h, SURFACE.nx, SURFACE.ny);
    m.water.material = new THREE.MeshPhongMaterial({
      color: CONFIG.colors.water, specular: 0xa8dbe6, shininess: 110, transparent: true, opacity: 0.2,
      side: THREE.DoubleSide, depthWrite: false, alphaMap: canvasTexture(128, (g, n) => drawEdgeFade(g, n, 0.12)), map: flow,
      normalMap: ripple, normalScale: new THREE.Vector2(0.55, 0.55),
    });
    addSecondRipple(m.water.material, rippleB);
    m.water.renderOrder = 2;

    const pool = new THREE.Group();
    pool.name = 'lc-pool';
    const layer = (w, h, z, material, order) => {
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), material);
      mesh.position.set(SURFACE.x, 0, z);
      mesh.renderOrder = order;
      pool.add(mesh);
      return mesh;
    };
    const flat = { transparent: true, depthWrite: false, alphaMap: edge };
    const tiles = canvasTexture(256, drawTiles, [SURFACE.w, SURFACE.h]);
    layer(SURFACE.w, SURFACE.h, FLOOR_Z, new THREE.MeshBasicMaterial({ ...flat, map: tiles }), -3);
    const glow = canvasTexture(128, drawCaustics);
    const caustics = [[4, 1.6, 0.07], [6.5, 2.6, 0.05]].map(([rx, ry, opacity], i) => {
      const map = glow.clone();
      map.wrapS = map.wrapT = THREE.RepeatWrapping;
      map.repeat.set(rx, ry);
      map.needsUpdate = true;
      layer(SURFACE.w, SURFACE.h, FLOOR_Z + 0.008 + 0.002 * i, new THREE.MeshBasicMaterial({
        ...flat, map, opacity, color: 0xbff6ff, blending: THREE.AdditiveBlending,
      }), -1);
      return map;
    });
    scene.add(pool);
    setupLighting(pool);
    const pos = m.water.geometry.attributes.position, a = pos.array;
    const fixed = new Float64Array(pos.count), heights = new Float64Array(pos.count);
    for (let i = 0; i < pos.count; i++) {
      const x = a[3 * i] + SURFACE.x, y = a[3 * i + 1], d = 0.55 - x;
      // Bow wave: a hump pushed up ahead of the head and a trough beside the shoulders.
      fixed[i] = 0.034 * Math.exp(-((x - 0.62) ** 2) / 0.025 - y * y / 0.04)
        - 0.022 * Math.exp(-((x - 0.3) ** 2) / 0.04 - y * y / 0.1);
      // Wake: two V-shaped wave trains spreading back from the shoulders.
      if (d > 0) {
        const wing = Math.abs(y) - 0.36 * d, width = 0.06 + 0.05 * d;
        fixed[i] += 0.016 * Math.exp(-d / 3.2 - (wing * wing) / (width * width)) * Math.cos(12 * d);
      }
    }
    // Separate fixed spatial terms from the changing wave phase.
    const waves = SWELL.map(([kx, ky, , amplitude]) => {
      const values = new Float64Array(2 * pos.count);
      for (let i = 0; i < pos.count; i++) {
        const phase = kx * (a[3 * i] + SURFACE.x) + ky * a[3 * i + 1];
        values[2 * i] = amplitude * Math.sin(phase);
        values[2 * i + 1] = amplitude * Math.cos(phase);
      }
      return values;
    });
    m.pool = { tiles, caustics, flow, ripple, rippleB, fixed, heights, waves, time: 0, dirty: true };
    return true;
  }

  // Move the swell, bow wave, wake, kick wash, and splash ripples, and scroll the floor back at
  // swim speed (so the pool slides past).
  function updateWater(m, P, dt) {
    if (!setupWater(m)) return;
    const pool = m.pool, t = (pool.time += dt), off = S.offset, fx = m.fx;
    const pos = m.water.geometry.attributes.position, a = pos.array;
    const pace = Math.min(1, P.speed), ripples = fx ? fx.ripples : [], wash = fx ? fx.wash : 0, footX = fx ? fx.footX : -1.6;
    if (dt === 0 && !pool.dirty && pool.pace === pace) return;
    const heights = pool.heights, [wave0, wave1, wave2] = pool.waves;
    const [c0, s0, c1, s1, c2, s2] = SWELL.flatMap(([kx, , kt]) => {
      const phase = kx * off + kt * t;
      return [Math.cos(phase), Math.sin(phase)];
    });
    for (let i = 0; i < pos.count; i++) {
      const x = a[3 * i] + SURFACE.x + off, y = a[3 * i + 1], lx = a[3 * i] + SURFACE.x;
      const j = 2 * i;
      let h = wave0[j] * c0 + wave0[j + 1] * s0 + wave1[j] * c1 + wave1[j + 1] * s1
        + wave2[j] * c2 + wave2[j + 1] * s2 + pool.fixed[i] * pace;
      // Kick wash: choppy water over and behind the feet that is carried back with the water.
      const behind = footX + 0.15 - lx;
      if (wash > 0.001 && behind > 0 && behind < 2) {
        const spread = 0.12 + 0.12 * behind;
        h += 0.007 * wash * Math.exp(-behind / 0.7 - (y * y) / (spread * spread))
          * Math.sin(17 * x + 9 * t) * Math.sin(13 * y - 6 * t);
      }
      heights[i] = h;
    }
    // Each ripple touches only a small patch of the surface, not every water vertex.
    const cols = SURFACE.nx + 1, sx = SURFACE.nx / SURFACE.w, sy = SURFACE.ny / SURFACE.h;
    for (const [rx, ry, age, strength] of ripples) {
      const front = FX.rippleSpeed * age + 0.03, outer = front + 0.3, inner = Math.max(0, front - 0.3);
      const minCol = Math.max(0, Math.floor((rx - outer - SURFACE.x + SURFACE.w / 2) * sx));
      const maxCol = Math.min(SURFACE.nx, Math.ceil((rx + outer - SURFACE.x + SURFACE.w / 2) * sx));
      const minRow = Math.max(0, Math.floor((SURFACE.h / 2 - ry - outer) * sy));
      const maxRow = Math.min(SURFACE.ny, Math.ceil((SURFACE.h / 2 - ry + outer) * sy));
      const amplitude = strength * Math.exp(-1.8 * age) / (1 + 4 * front);
      for (let row = minRow; row <= maxRow; row++) {
        const dy = a[3 * row * cols + 1] - ry;
        for (let col = minCol; col <= maxCol; col++) {
          const i = row * cols + col, dx = a[3 * i] + SURFACE.x - rx, distanceSq = dx * dx + dy * dy;
          if (distanceSq < inner * inner || distanceSq > outer * outer) continue;
          const gap = Math.sqrt(distanceSq) - front;
          heights[i] += amplitude * Math.exp(-(gap * gap) / 0.012) * Math.cos(20 * gap);
        }
      }
    }
    for (let i = 0; i < pos.count; i++) a[3 * i + 2] = heights[i];
    pos.needsUpdate = true;
    m.water.geometry.computeVertexNormals();
    pool.dirty = false;
    pool.pace = pace;
    pool.tiles.offset.x = wrap(off);
    // Positive UV offset moves the streaks back across the swimmer-relative surface.
    pool.flow.offset.x = wrap(off * pool.flow.repeat.x / SURFACE.w);
    // Ripples ride back with the pool water and drift slowly; the second layer crosses them.
    pool.ripple.offset.set(wrap(off / RIPPLE_TILE + 0.05 * t), wrap(0.03 * t));
    pool.rippleB.value.x = wrap(off * 1.73 / RIPPLE_TILE - 0.04 * t);
    pool.rippleB.value.y = wrap(-0.06 * t);
    pool.caustics.forEach((map, i) => {
      const r = map.repeat.x / SURFACE.w, s = i ? -1 : 1;
      map.offset.set(wrap(off * r + 0.02 * s * t), wrap(0.015 * t * s));
    });
  }

  // ---- water reaction ---------------------------------------------------------

  // The water answers the swimmer's measured limb motion, so the controls drive it indirectly:
  // a faster rate or steeper entry hits the surface harder, slip makes the pulling hand churn
  // bubbles instead of holding still water, and a bigger or knee-led kick breaks the surface more.
  // Visual only: nothing here feeds back into the phase, the pose, or the metrics.
  // Positions are in the swimmer's frame, where the still pool water streams back at swim speed.
  // Particles are [x, y, z, vx, vy, vz, age, life].
  const FX = {
    maxRipples: 24, maxBubbles: 420, maxSpray: 160, maxPressure: 700, rippleSpeed: 0.55, gravity: 9.81, rise: 0.28,
  };
  const rand = (a, b) => a + (b - a) * Math.random();
  const spawnCount = rate => Math.floor(rate + Math.random());

  // Simulated pressure view (visual only). Probes on each palm, forearm, and instep measure how
  // hard that surface is moving into the water ahead of it; loaded water is released as a warm
  // cloud pushed the way the surface drives it, which the stream then carries back, spreads, cools,
  // and dissipates. `face` is the surface normal in the joint frame (palm and instep face local -z);
  // a forearm is round, so it loads the water on whichever side it moves toward.
  const PRESSURE = {
    hot: [1.0, 0.6, 0.22], cool: [0.55, 0.82, 1.0],
    probes: ['R', 'L'].flatMap(s => [
      { joint: 'wr' + s, at: [0.065, 0, -0.02], face: [0, 0, -1], gain: 1, hand: true },
      { joint: 'el' + s, at: [0.15, 0, 0], face: null, gain: 0.45, hand: true },
      { joint: 'ankle' + s, at: [-0.07, 0, -0.02], face: [0, 0, -1], gain: 0.5, hand: false },
    ]),
  };

  function updatePressure(fx, m, dt, slipness, flow) {
    const sys = fx.pressure;
    for (const pr of fx.probes) {
      const joint = m[pr.joint];
      joint.localToWorld(pr.pos.set(...pr.at));
      if (pr.known) pr.vel.subVectors(pr.pos, pr.prev).divideScalar(dt);
      pr.prev.copy(pr.pos);
      const wasKnown = pr.known;
      pr.known = true;
      if (!wasKnown || pr.pos.z > -0.03) continue;
      // Load follows the limb's push relative to the body: a hand that holds the water stays nearly
      // still in it while the body moves past, so the push it makes is what loads the water.
      if (pr.face) {
        pr.n.set(...pr.face).transformDirection(joint.matrixWorld);
      } else {
        pr.axis.set(1, 0, 0).transformDirection(joint.matrixWorld);
        pr.n.copy(pr.vel).addScaledVector(pr.axis, -pr.vel.dot(pr.axis));
        if (pr.n.lengthSq() < 1e-6) continue;
        pr.n.normalize();
      }
      const q = Math.max(0, pr.vel.dot(pr.n));
      // A slipping hand moves fast but builds little pressure: the water slides off it instead.
      const hold = pr.hand ? 1 - 0.9 * slipness : 1;
      const rate = Math.min(320, 90 * pr.gain * hold * q * q);
      for (let i = spawnCount(rate * dt); i > 0; i--) {
        const push = 0.55 * q * rand(0.6, 1.1);
        emit(sys, pr.pos.x + 0.03 * pr.n.x + rand(-0.03, 0.03), pr.pos.y + 0.03 * pr.n.y + rand(-0.03, 0.03),
          pr.pos.z + 0.03 * pr.n.z + rand(-0.02, 0.02),
          -flow + push * pr.n.x + rand(-0.15, 0.15), push * pr.n.y + rand(-0.15, 0.15), push * pr.n.z + rand(-0.1, 0.1),
          rand(0.8, 1.4), clamp(0.35 + 0.35 * q, 0.35, 1));
      }
    }
  }

  // Fresh pressure glows warm and dense; as it spreads and slows it cools to pale blue and fades.
  function drawPressure(sys) {
    const [hr, hg, hb] = PRESSURE.hot, [cr, cg, cb] = PRESSURE.cool, list = sys.list;
    for (let i = 0; i < list.length; i++) {
      const q = list[i], age = q[6] / q[7], cool = smooth(clamp(age * 1.6, 0, 1));
      const alpha = 0.5 * (q[8] ?? 1) * Math.min(1, q[6] / 0.06) * (1 - age) ** 1.4;
      sys.pos[3 * i] = q[0]; sys.pos[3 * i + 1] = q[1]; sys.pos[3 * i + 2] = q[2];
      sys.col[4 * i] = lerp(hr, cr, cool); sys.col[4 * i + 1] = lerp(hg, cg, cool); sys.col[4 * i + 2] = lerp(hb, cb, cool);
      sys.col[4 * i + 3] = alpha;
    }
    sys.geo.attributes.position.needsUpdate = true;
    sys.geo.attributes.color.needsUpdate = true;
    sys.geo.setDrawRange(0, list.length);
  }

  function makeParticles(group, max, size, color) {
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(max * 3), col = new Float32Array(max * 4);
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 4).setUsage(THREE.DynamicDrawUsage));
    geo.setDrawRange(0, 0);
    S.puff = S.puff || puffTexture();
    const points = new THREE.Points(geo, new THREE.PointsMaterial({
      size, map: S.puff, vertexColors: true, transparent: true, depthWrite: false,
    }));
    points.frustumCulled = false;
    points.renderOrder = 4;
    group.add(points);
    return { max, list: [], geo, pos, col, color, points };
  }

  // Build the ripple list, particle systems, and per-limb trackers once per scene.
  function setupSplash(m) {
    if (m.fx) return m.fx;
    const scene = S.el.scene, old = scene.getObjectByName('lc-water-fx');
    if (old) scene.remove(old);
    const group = new THREE.Group();
    group.name = 'lc-water-fx';
    scene.add(group);
    m.fx = {
      ripples: [], wash: 0, footX: -1.6,
      bubbles: makeParticles(group, FX.maxBubbles, 0.05, [0.85, 0.96, 1]),
      spray: makeParticles(group, FX.maxSpray, 0.045, [1, 1, 1]),
      pressure: makeParticles(group, FX.maxPressure, 0.18, PRESSURE.hot),
      limbs: ALL_LIMBS.map(limb => ({
        limb, hand: limb.key.startsWith('hand'), known: false, air: 0, wet: 0,
        pos: new THREE.Vector3(), prev: new THREE.Vector3(), vel: new THREE.Vector3(),
      })),
      probes: PRESSURE.probes.map(probe => ({
        ...probe, known: false,
        pos: new THREE.Vector3(), prev: new THREE.Vector3(), vel: new THREE.Vector3(),
        n: new THREE.Vector3(), axis: new THREE.Vector3(),
      })),
    };
    m.fx.pressure.points.material.blending = THREE.AdditiveBlending;
    return m.fx;
  }

  function emit(sys, x, y, z, vx, vy, vz, life, strength = 1) {
    if (sys.list.length < sys.max) sys.list.push([x, y, z, vx, vy, vz, 0, life, strength]);
  }

  function ripple(fx, x, y, strength) {
    if (fx.ripples.length >= FX.maxRipples) fx.ripples.shift();
    fx.ripples.push([x, y, 0, Math.min(strength, 0.014)]);
  }

  // Surface crossings, carried air, slip churn, and kick wash for one fingertip or toe.
  // `vel` is the limb's velocity in the swimmer's frame; relative to the water add the swim speed to x.
  function limbWater(fx, l, P, dt, slipness, flow) {
    const p = l.pos, v = l.vel, speed = v.length();
    if (l.prev.z > 0 && p.z <= 0) {
      // Entry: a harder, more vertical hit throws more spray and a bigger ring, and drags air down.
      const impact = Math.max(0, -v.z) + 0.25 * speed;
      ripple(fx, p.x, p.y, 0.004 + 0.005 * impact);
      const n = Math.round(clamp((l.hand ? 3 : 1) + 5 * impact, 0, 16));
      for (let i = 0; i < n; i++) {
        emit(fx.spray, p.x, p.y, 0.01, -0.5 * flow + rand(-0.4, 0.4), rand(-0.45, 0.45), rand(0.35, 0.6 + 0.6 * impact), 0.7);
      }
      l.air = clamp(0.3 + 0.5 * impact, 0, 1.2);
    } else if (l.prev.z <= 0 && p.z > 0) {
      // Exit: a smaller ring, and water left on the hand drips off during the recovery.
      ripple(fx, p.x, p.y, 0.003 + 0.002 * speed);
      l.wet = l.hand ? 1 : 0.4;
    }
    if (p.z > 0.02 && l.wet > 0) {
      // Drips leave with the hand's own velocity and then fall freely.
      for (let i = spawnCount(30 * l.wet * dt); i > 0; i--) {
        emit(fx.spray, p.x, p.y + rand(-0.02, 0.02), p.z, v.x, v.y, v.z, 0.9);
      }
    }
    l.wet = Math.max(0, l.wet - 1.6 * dt);
    if (p.z >= 0) return;
    let rate = 70 * l.air;
    if (l.hand) {
      // A held catch barely disturbs the water; a slipping hand tears through it pushing back.
      rate += 140 * slipness * clamp(-v.x - 0.4, 0, 2);
    } else {
      const near = clamp(1 + p.z / 0.25, 0, 1);
      fx.washTarget += near * Math.abs(v.z);
      rate += 40 * P.kick * near * clamp(Math.abs(v.z) - 0.5, 0, 2);
    }
    l.air = Math.max(0, l.air - 2.5 * dt);
    for (let i = spawnCount(rate * dt); i > 0; i--) {
      // Bubbles start near the water's own velocity and keep a little of the limb's push.
      emit(fx.bubbles, p.x + rand(-0.03, 0.03), p.y + rand(-0.03, 0.03), p.z + rand(-0.02, 0.02),
        -flow + 0.3 * (v.x + flow), 0.3 * v.y + rand(-0.1, 0.1), 0.3 * v.z, rand(1.2, 2.2));
    }
  }

  // Keep the particles for which `keep` returns true, in place.
  function compact(list, keep) {
    let n = 0;
    for (const q of list) if (keep(q)) list[n++] = q;
    list.length = n;
  }

  function stepFx(fx, flow, dt) {
    const drag = Math.min(1, 4 * dt);
    // Bubbles: the water drags them back toward its own speed while buoyancy settles them into a
    // slow wobbling rise; they burst with a tiny ring at the surface.
    compact(fx.bubbles.list, q => {
      q[3] += (-flow - q[3]) * drag;
      q[4] += -q[4] * drag + rand(-0.6, 0.6) * dt;
      q[5] += (FX.rise - q[5]) * Math.min(1, 3 * dt);
      q[0] += q[3] * dt; q[1] += q[4] * dt; q[2] += q[5] * dt; q[6] += dt;
      if (q[2] > -0.005) {
        if (Math.random() < 0.05) ripple(fx, q[0], q[1], 0.0012);
        return false;
      }
      return q[6] < q[7];
    });
    // Spray and drips: ballistic under gravity until they land back in the water.
    compact(fx.spray.list, q => {
      q[5] -= FX.gravity * dt;
      q[0] += q[3] * dt; q[1] += q[4] * dt; q[2] += q[5] * dt; q[6] += dt;
      if (q[2] < 0) {
        if (Math.random() < 0.08) ripple(fx, q[0], q[1], 0.0015);
        return false;
      }
      return q[6] < q[7];
    });
    // Pressure: the pushed water slows into the surrounding stream and is carried back with it.
    const settle = Math.min(1, 2.5 * dt);
    compact(fx.pressure.list, q => {
      q[3] += (-flow - q[3]) * settle; q[4] -= q[4] * settle; q[5] -= q[5] * settle;
      q[0] += q[3] * dt; q[1] += q[4] * dt; q[2] = Math.min(-0.01, q[2] + q[5] * dt); q[6] += dt;
      return q[6] < q[7];
    });
    // Rings ride back with the water and are dropped once they have faded.
    for (const r of fx.ripples) { r[0] -= flow * dt; r[2] += dt; }
    compact(fx.ripples, r => r[2] < 2.2);
  }

  function drawParticles(sys, alpha) {
    const [r, g, b] = sys.color, list = sys.list;
    for (let i = 0; i < list.length; i++) {
      const q = list[i], fade = Math.min(1, 3 * (1 - q[6] / q[7]));
      sys.pos[3 * i] = q[0]; sys.pos[3 * i + 1] = q[1]; sys.pos[3 * i + 2] = q[2];
      sys.col[4 * i] = r; sys.col[4 * i + 1] = g; sys.col[4 * i + 2] = b; sys.col[4 * i + 3] = alpha * fade;
    }
    sys.geo.attributes.position.needsUpdate = true;
    sys.geo.attributes.color.needsUpdate = true;
    sys.geo.setDrawRange(0, list.length);
  }

  // Measure each limb, react to the water, and advance ripples and particles; frozen while paused.
  function updateSplash(m, P, dt, slipness) {
    if (!m.pool) return;
    const fx = setupSplash(m), flow = S.flow ?? P.speed;
    if (S.trailReset) {
      fx.ripples.length = fx.bubbles.list.length = fx.spray.list.length = fx.pressure.list.length = 0;
      fx.wash = 0;
      m.pool.dirty = true;
      for (const l of fx.limbs) { l.known = false; l.air = l.wet = 0; }
      for (const pr of fx.probes) pr.known = false;
    }
    if (dt > 0) {
      fx.washTarget = 0;
      let feetX = 0, feet = 0;
      for (const l of fx.limbs) {
        m[l.limb.joint].localToWorld(l.pos.set(...l.limb.tip));
        if (l.known) {
          l.vel.subVectors(l.pos, l.prev).divideScalar(dt);
          limbWater(fx, l, P, dt, slipness, flow);
        }
        if (!l.hand) { feetX += l.pos.x; feet++; }
        l.prev.copy(l.pos);
        l.known = true;
      }
      fx.footX = feetX / feet;
      fx.wash += (clamp(fx.washTarget / 2, 0, 1.5) - fx.wash) * Math.min(1, 3 * dt);
      if (P.pressure) updatePressure(fx, m, dt, slipness, flow);
      stepFx(fx, flow, dt);
    }
    if (!P.pressure) fx.pressure.list.length = 0;
    drawParticles(fx.bubbles, 0.7);
    drawParticles(fx.spray, 0.9);
    drawPressure(fx.pressure);
  }

  // ---- split view -------------------------------------------------------------

  // Extra scene views share the scene; the engine aims their camera from a preset angle and keeps it fitted.
  // dir: camera direction from the target; up: screen-up axis; half: half-extent (w, h) to keep in frame.
  const VIEWS = {
    top: { dir: [0, 0, 1], up: [1, 0, 0], half: [0.62, 1.3] },
    below: { dir: [0, 0, -1], up: [1, 0, 0], half: [0.62, 1.3] },
    side: { dir: [0, -1, 0], up: [0, 0, 1], half: [1.3, 0.5] },
    front: { dir: [1, 0, 0.18], up: [0, 0, 1], half: [0.7, 0.5], min: 3.4 },
  };
  // Adopt a scene_view as the second camera; retries until NiceGUI has mounted it.
  function setView(viewId, angle) {
    const el = typeof getElement === 'function' ? getElement(viewId) : null;
    if (!el || !el.renderer || !el.camera) { setTimeout(() => setView(viewId, angle), 100); return; }
    if (!S.view || S.view.el !== el) {
      el.renderer.setClearColor(CONFIG.background);
      el.$el.style.width = '100%';
      el.$el.style.height = '100%';
      const v = el.camera.position.clone();
      S.view = { el, dir: v.clone(), target: v.clone().set(-0.25, 0, -0.12) };
    }
    S.view.angle = angle;
  }

  // Place the second camera so the swimmer fills its pane at the chosen angle (runs every frame).
  function fitView() {
    const v = S.view;
    if (!v) return;
    const el = v.el, cam = el.camera, spec = VIEWS[v.angle] || VIEWS.top;
    const w = el.$el.clientWidth, h = el.$el.clientHeight;
    if (!w || !h) return;
    if (el.camera_tween) { el.camera_tween.stop(); el.camera_tween = null; }
    const t = Math.tan(cam.fov * D / 2);
    const dist = Math.max(spec.min || 0, 1.15 * spec.half[1] / t, 1.15 * spec.half[0] / (t * w / h));
    v.dir.set(...spec.dir).normalize();
    cam.up.set(...spec.up);
    cam.position.copy(v.target).addScaledVector(v.dir, dist);
    cam.lookAt(v.target);
  }

  // ---- posing -----------------------------------------------------------------

  // Underwater forearm and hand fade from teal (holding) to red (slipping); skin colour in the air.
  function paint(mesh, under, slipness) {
    const col = under ? C.hold.map((v, i) => lerp(v, C.slip[i], slipness)) : C.skin;
    mesh.material.color.setRGB(col[0], col[1], col[2]);
  }

  // Emphasis overlay opacity; sqrt keeps weak contributions visible.
  function patch(mesh, value) {
    mesh.material.opacity = clamp(Math.sqrt(Math.max(0, value)) * 0.85, 0, 0.85);
    mesh.visible = value > 0.02;
  }

  // Fixed-length two-bone inverse kinematics for one arm in the rolled chest frame.
  function poseArm(m, side, a, P, slipness, bodyRoll, pitch = 0) {
    const sgn = side === 'R' ? -1 : 1, sh = m['sh' + side], r = m.rigs[side];
    const cos = Math.cos(bodyRoll), sin = Math.sin(bodyRoll);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    sh.position.x = r.baseX + 0.04 * a.shrug;
    // Keep the hand's lane-relative width and water-relative depth independent of body roll.
    // Transform both together: correcting depth alone lets a deep pull cross the centre line.
    const toChestPoint = (v, x, out, height) => {
      const y = sh.position.y * cos + sgn * out;
      const z = (height + 0.06 - m.chest.position.z + (sh.position.x + x) * sp) / cp;
      return v.set(x, y * cos + z * sin - sh.position.y, -y * sin + z * cos);
    };
    toChestPoint(r.target, a.x, a.out, a.height);
    const reach = softReach(r.target.length(), lerp(PULL_REACH, MIN_REACH, a.recovery));
    r.axis.copy(r.target).normalize();
    r.target.copy(r.axis).multiplyScalar(reach);
    // Body-frame direction [forward, outward, up] → rolled chest frame. Under water the guide mostly
    // follows the chest: with the body rolled onto the pulling side a world-referenced "out and up"
    // would point straight back along a hand hanging below the shoulder and leave no bend direction.
    // In the recovery it follows the world so the elbow leads up out of the water.
    const guideRoll = bodyRoll * lerp(0.4, 1, a.recovery);
    const gc = Math.cos(guideRoll), gs = Math.sin(guideRoll);
    const toChest = (v, [f, o, u], c = gc, s = gs) => v.set(f, sgn * o * c + u * s, -sgn * o * s + u * c);
    toChest(r.pole, a.elbowDir);
    r.pole.addScaledVector(r.axis, -r.pole.dot(r.axis));
    // A guide nearly along the shoulder-hand line (hand tucked under the chest, or a wide shallow
    // pull) leaves almost no bend direction, and its remainder can swap fore and aft. Keep a soft
    // minimum share toward "out and a little forward" so the bend direction never passes through zero.
    r.hint.set(0.5, sgn, 0);
    r.hint.addScaledVector(r.axis, -r.hint.dot(r.axis)).normalize();
    const share = r.pole.dot(r.hint), floor = 0.25;
    const kept = 0.5 * (share + floor + Math.sqrt((share - floor) ** 2 + 0.01));
    r.pole.addScaledVector(r.hint, kept - share).normalize();
    if (a.recovery > 0) {
      const [ex, eo, eh] = a.elbow;
      toChestPoint(r.hint, ex, eo, eh);
      r.hint.addScaledVector(r.axis, -r.hint.dot(r.axis));
      // A guide lying on the shoulder-wrist line has no direction; keep the world-up guide then.
      const weight = a.recovery * smooth(clamp(r.hint.length() / 0.08, 0, 1));
      r.pole.lerp(r.hint.normalize(), weight).addScaledVector(r.axis, -r.pole.dot(r.axis)).normalize();
    }
    const along = (UPPER ** 2 - FOREARM ** 2 + reach ** 2) / (2 * reach);
    const lift = Math.sqrt(Math.max(0, UPPER ** 2 - along ** 2));
    // Bound elbow position, not its bend direction: recovery may fold inward without crossing the torso.
    r.z.set(0, sgn, 0).addScaledVector(r.axis, -sgn * r.axis.y).normalize();
    const minOut = clamp((0.015 - along * sgn * r.axis.y) / (lift * Math.sqrt(1 - r.axis.y ** 2)), -1, 1);
    const outward = r.pole.dot(r.z);
    if (outward < minOut) {
      // Keep the guide's fore/aft remainder unnormalised. When the guide points almost straight
      // inward that remainder shrinks through zero and changes sign; the growing outward share
      // then swings the elbow out to the side instead of snapping it from front to back.
      r.normal.copy(r.pole).addScaledVector(r.z, -outward);
      const spare = r.normal.length();
      const keep = (minOut * spare) / Math.sqrt(Math.max(1e-3, 1 - minOut ** 2));
      r.pole.copy(r.normal).addScaledVector(r.z, keep + 0.8 * Math.max(0, 0.6 - spare)).normalize();
    }
    r.elbow.copy(r.axis).multiplyScalar(along).addScaledVector(r.pole, lift);
    r.upper.copy(r.elbow).normalize();
    r.lower.copy(r.target).sub(r.elbow).normalize();
    // Both bones share one bend-plane normal: the elbow is a hinge, not another shoulder.
    r.normal.crossVectors(r.pole, r.axis).normalize();
    r.z.crossVectors(r.upper, r.normal);
    r.matrix.makeBasis(r.upper, r.normal, r.z);
    sh.quaternion.setFromRotationMatrix(r.matrix);
    r.z.crossVectors(r.lower, r.normal);
    r.matrix.makeBasis(r.lower, r.normal, r.z);
    r.quaternion.setFromRotationMatrix(r.matrix);
    m['el' + side].quaternion.copy(sh.quaternion).invert().multiply(r.quaternion);
    // Forearm rotation (pronation/supination) about the forearm's own axis. With no twist the palm
    // faces the elbow crease; turn it toward the phase's palm direction, within the joint's range.
    toChest(r.hint, a.palm, cos, sin).addScaledVector(r.lower, -r.hint.dot(r.lower));
    // Fold the angle back to zero near ±180° (both sides then agree) and fade it when the palm
    // target runs along the forearm, so the hand never snaps from one side to the other.
    const raw = Math.atan2(r.hint.dot(r.normal), -r.hint.dot(r.z)), lim = 135 * D;
    const folded = Math.abs(raw) <= lim ? raw : (Math.sign(raw) * lim * (Math.PI - Math.abs(raw))) / (Math.PI - lim);
    const twist = folded * smooth(clamp(r.hint.length() / 0.3, 0, 1));
    r.twist = twist;
    m['wr' + side].rotation.set(twist, a.wrist, 0);
    paint(m['fa' + side], a.under, slipness);
    paint(m['ha' + side], a.under, slipness);
    paint(m['thumb' + side], a.under, slipness);
  }

  // Two-beat kick, per leg: a quick downbeat from a slightly bent knee that snaps straight, then a
  // slow, relaxed upbeat while the body glides. q is the time since this leg's downbeat began.
  const TWO_BEAT = {
    hip: [[0, 0.20], [0.13, -0.26], [0.30, -0.12], [0.75, 0.10], [1, 0.20]],
    knee: [[0, 0.40], [0.08, 0.16], [0.14, 0.0], [0.6, 0.04], [0.88, 0.28], [1, 0.40]],
    ankle: [[0, 0], [0.07, 1], [0.16, 0.2], [0.4, 0], [1, 0]],
  };
  // The left leg's downbeat starts just before the right hand enters, so it lands with the right
  // catch (opposite leg, opposite arm) and rotates the hips onto the right side; the right leg mirrors it.
  const KICK_START = 0.94;

  // 0 for a six-beat flutter, 1 for a two-beat kick that drives the roll; a knee kick loses that link.
  const kickTiming = (P, F) => (F.kneekick ? 0 : clamp((6 - (P.beats ?? 6)) / 4, 0, 1));

  // Healthy kicks drive from the hips; a knee kick drops the thighs and bends the knees hard.
  // Each beat varies a little in size and timing (t is stroke time; zero kick stays still).
  function poseLegs(m, P, F, t) {
    const knees = F.kneekick ? 1 : 0, base = knees ? Math.max(P.kick, 0.6) : P.kick;
    const beats = knees ? 6 : P.beats ?? 6;
    const kick = 2 * Math.PI * (beats / 2) * S.phase;
    for (const [side, offset] of [['R', 0], ['L', Math.PI]]) {
      const k = base * (1 + 0.12 * noise(3 * t, offset ? 52 : 51));
      if (beats === 2 && !knees) {
        // Bigger single beats: the downbeat has to turn the hips as well as balance the legs.
        const q = wrap(S.phase - P.catchDelay - KICK_START - (offset ? 0 : 0.5)
          + 0.01 * noise(2 * t, offset ? 62 : 61));
        const big = 1.25 * k;
        m['leg' + side].rotation.set(0, big * keyed(q, TWO_BEAT.hip), 0);
        m['knee' + side].rotation.set(0, big * keyed(q, TWO_BEAT.knee), 0);
        m['ankle' + side].rotation.set(0, -0.12 - 0.35 * big * keyed(q, TWO_BEAT.ankle), 0);
        continue;
      }
      const angle = kick + offset + 0.15 * noise(2 * t, offset ? 62 : 61);
      const hip = knees ? -0.12 * k + 0.06 * k * Math.sin(angle) : 0.26 * k * Math.sin(angle);
      const knee = knees ? 0.2 + 1.3 * k * Math.max(0, Math.sin(angle - 0.3)) : 0.45 * k * Math.max(0, Math.sin(angle - 0.7));
      m['leg' + side].rotation.set(0, hip, 0);
      m['knee' + side].rotation.set(0, knee, 0);
      m['ankle' + side].rotation.set(0, -0.12 + k * (knees ? 0.25 : 0.10) * Math.sin(angle - 0.5), 0);
    }
  }

  // Kick-driven roll for the two-beat timing: each downbeat flips the hips to the next side in
  // about a fifth of a cycle, and they hold there (a short glide on the side) until the next beat.
  // Returns -1..1 with +1 = right side down.
  function kickRoll(p) {
    const q = wrap(p - KICK_START), turn = 0.2;
    if (q < turn) return -1 + 2 * smooth(q / turn);
    if (q < 0.5) return 1;
    if (q < 0.5 + turn) return 1 - 2 * smooth((q - 0.5) / turn);
    return -1;
  }

  // ---- HUD and input ----------------------------------------------------------

  // DOM lookups are cached and writes skipped when unchanged to keep frames cheap.
  function find(key, selector) {
    const cached = S.ui[key];
    if (cached && cached.isConnected) return cached;
    S.ui[key] = document.querySelector(root)?.querySelector(selector);
    return S.ui[key];
  }

  function setText(key, selector, text) {
    if (S.ui[key + 'Text'] === text) return;
    const node = find(key, selector);
    if (node) { node.textContent = text; S.ui[key + 'Text'] = text; }
  }

  // Arm-phase labels, cycle percentage, and timeline marker.
  function updateHud(right, left) {
    setText('right', '.lc-arm-right', PHASES[right.stage]);
    setText('left', '.lc-arm-left', PHASES[left.stage]);
    setText('cycle', '.lc-cycle', Math.floor(S.phase * 100 + 1e-8) % 100 + '%');
    const marker = find('marker', '.lc-timeline-marker');
    const position = (S.phase * 100).toFixed(1) + '%';
    if (marker && S.ui.markerAt !== position) { marker.style.left = position; S.ui.markerAt = position; }
    const timeline = find('timeline', '.lc-timeline');
    if (timeline && timeline.dataset.stage !== String(right.stage)) timeline.dataset.stage = right.stage;
    const percent = String(Math.floor(S.phase * 100));
    if (timeline && timeline.getAttribute('aria-valuenow') !== percent) {
      timeline.setAttribute('aria-valuenow', percent);
      timeline.setAttribute('aria-valuetext', `${PHASES[right.stage]}, ${percent}% of right-arm cycle`);
    }
  }

  // ---- frame loop -------------------------------------------------------------

  // Advance the phase, then pose body, arms, legs, overlays, trails, and lane ropes.
  function frame(t) {
    requestAnimationFrame(frame);
    if (document.hidden || !S.active || !S.params) { S.last = null; return; }
    const dt = S.last === null ? 0 : Math.min(0.1, (t - S.last) / 1000);
    S.last = t;
    const P = S.params;
    const scaled = P.playing && !S.seekPausePending ? dt * (P.playback || 1) : 0;
    advance(scaled);
  }

  // Lightweight visual reactions, not a calibrated fluid solver. Sample the prescribed stroke in
  // a neutral body frame so yesterday's reaction never becomes today's limb impulse.
  function moveThroughWater(m, P, dt, slipness, breath, oldX, resetMotion) {
    const body = m.chest.parent;
    if (!m.motion || resetMotion) {
      m.motion = {speed: P.speed, load: 0.35 * (1 - 0.9 * slipness), surge: 0, yaw: 0, turn: 0, sway: 0, drift: 0,
        height: 0, rise: 0, pitch: 0, pitchRate: 0};
      for (const p of m.probes) p.known = false;
    }
    const s = m.motion;
    let forward = 0, sideways = 0, vertical = 0, torque = 0, tipping = 0, kickDrive = 0;
    body.updateMatrixWorld(true);
    for (const p of m.probes) {
      const joint = m[p.joint];
      joint.localToWorld(p.pos.set(...p.at));
      if (dt > 0 && p.known) {
        p.velocity.subVectors(p.pos, p.prev).divideScalar(dt).clampLength(0, 3);
        const downbeat = Math.max(0, -p.velocity.z);
        // The pool is still: include body travel, sideways drift and vertical motion.
        p.velocity.x += s.speed;
        p.velocity.y += s.drift;
        p.velocity.z += s.rise;
        if (p.face) {
          p.normal.set(...p.face).transformDirection(joint.matrixWorld);
        } else {
          p.axis.set(1, 0, 0).transformDirection(joint.matrixWorld);
          p.normal.copy(p.velocity).addScaledVector(p.axis, -p.velocity.dot(p.axis)).normalize();
        }
        const q = p.velocity.dot(p.normal);
        const wet = smooth(clamp(-(p.pos.z + s.height) / 0.06, 0, 1));
        const grip = p.hand ? (1 - 0.9 * slipness) * (0.35 + 0.65 * P.catch) : 0.2 * P.kick;
        const load = -p.gain * wet * grip * q * Math.abs(q);
        const fx = load * p.normal.x, fy = load * p.normal.y, fz = load * p.normal.z;
        if (p.hand) forward += fx;
        else {
          const knee = m[p.joint === 'ankleR' ? 'kneeR' : 'kneeL'].rotation.y;
          // A small paddle approximation: submerged downbeats help, deeply bent knees waste them.
          kickDrive += wet * P.kick * downbeat ** 2 * p.normal.z ** 2 / (1 + 4 * knee ** 2);
        }
        sideways += fy;
        vertical += fz;
        torque += p.pos.x * fy - p.pos.y * fx;
        tipping += p.pos.z * fx - p.pos.x * fz;
      }
      if (dt > 0 || !p.known) {
        p.prev.copy(p.pos);
        p.known = true;
      }
    }
    // Calibrate on arms only so kick changes aren't averaged away. Kick thrust is capped at
    // 16% of the reference arm load; exposed thighs and bent knees also add a little resistance.
    const legDrag = ['R', 'L'].reduce((sum, side) => sum + Math.sin(m['leg' + side].rotation.y) ** 2
      + Math.sin(m['knee' + side].rotation.y) ** 2, 0);
    const dragShape = 1 + 2 * P.hipDrop + (S.faults.sinking ? 0.35 : 0)
      + 2 * Math.abs(s.pitch) + 0.12 * legDrag;
    const steps = Math.ceil(dt * 120), h = steps ? dt / steps : 0;
    for (let i = 0; i < steps; i++) {
      s.load += (Math.max(0, forward) - s.load) * (1 - Math.exp(-h * P.rate / 240));
      const drag = 0.6 * Math.max(0.015, s.load) * dragShape / Math.max(0.04, P.speed ** 2);
      const kickThrust = 0.16 * Math.max(0.015, s.load) * Math.tanh(kickDrive / 0.12);
      s.speed = clamp(s.speed + (0.6 * (forward + kickThrust) - drag * s.speed ** 2) * h,
        0.15 * P.speed, 1.7 * P.speed);
      s.surge += (s.speed - P.speed - 1.3 * s.surge) * h;
      s.turn += (2.4 * torque - 5 * s.turn) * h;
      s.yaw += s.turn * h;
      s.drift += (0.8 * sideways + s.speed * Math.sin(4 * D * Math.tanh(s.yaw / (4 * D)))
        - 4 * s.drift) * h;
      s.sway += s.drift * h;
      s.rise += (0.12 * vertical + 22 * (0.006 * Math.abs(breath) - s.height) - 7 * s.rise) * h;
      s.height += s.rise * h;
      s.pitchRate += (0.14 * tipping - 18 * (s.pitch + 0.7 * D * Math.abs(breath)) - 6 * s.pitchRate) * h;
      s.pitch += s.pitchRate * h;
    }
    // A follow-frame window bounds the illustration, not a spring pulling him to lane centre.
    body.rotation.set(0, 2 * D * Math.tanh(s.pitch / (2 * D)), 4 * D * Math.tanh(s.yaw / (4 * D)));
    body.position.x = m.bodyOrigin.x + 0.14 * Math.tanh(s.surge / 0.14);
    body.position.y = m.bodyOrigin.y + 0.18 * Math.tanh(s.sway / 0.18);
    body.position.z = m.bodyOrigin.z + 0.025 * Math.tanh(s.height / 0.025);
    S.flow = s.speed;
    // Translation plus the scrolling pool must add up to travel, not count the surge twice.
    if (dt > 0) S.offset += s.speed * dt - (body.position.x - oldX);
    body.updateMatrixWorld(true);
  }

  function poseSwimmer(P, m, scaled, resetMotion) {
    // Measure the prescribed stroke in a neutral frame, never the previous steering response.
    const previousX = m.chest.parent.position.x;
    m.chest.parent.rotation.set(0, 0, 0);
    m.chest.parent.position.copy(m.bodyOrigin);
    if (scaled > 0) {
      const next = S.phase + scaled / (120 / P.rate);
      S.cycles += Math.floor(next);
      S.phase = next % 1;
    }
    // Exponential settling is stable at any frame rate and freezes with the stroke clock.
    if (!S.ride) S.ride = {height: P.rideHeight, hips: P.hipDrop};
    const settle = 1 - Math.exp(-4 * scaled);
    S.ride.height = lerp(S.ride.height, P.rideHeight, settle);
    S.ride.hips = lerp(S.ride.hips, P.hipDrop, settle);
    // Body roll: positive = right shoulder down, deepest at the right catch. Connected drive lets the hips lead.
    // Flat hips moves the rotation into the shoulders; sinking legs pitches the chest up and the pelvis down.
    // Breathing deepens the roll a few degrees toward the breathing side; roll size also wanders slightly.
    const F = S.faults, w = 2 * Math.PI, st = S.cycles + S.phase, breath = breathing(P);
    const chestGain = F.overrotation ? 1.65 : F.flathips ? 1.25 : 1;
    const roll = Math.min(80, P.roll * chestGain * (1 + 0.04 * noise(2 * st, 11))) * D;
    const lead = 0.07 * P.drive - 0.05 * (1 - P.drive);
    const hipShare = F.flathips ? 0.06 : F.overrotation ? 0.85 : 0.3 + 0.6 * P.drive;
    // Two-beat timing: the kick turns the hips first and the chest follows a moment later, then both
    // hold on the side. A six-beat kick leaves the steady, even rotation.
    const sharp = kickTiming(P, F);
    const rollAt = p => lerp(Math.cos(w * (p - ROLL_PEAK)), kickRoll(p - P.catchDelay), sharp);
    const bodyRoll = roll * rollAt(S.phase - 0.04 * sharp) + 6 * D * breath;
    const pitch = F.sinking ? -14 * D : 0, legPitch = F.sinking ? -24 * D : 0;
    // Snaking: the chest yaws with each sweep and the hips swing the other way behind it.
    const yaw = (F.snaking ? 7 * D * Math.sin(w * (S.phase - ROLL_PEAK)) : 0) + 0.8 * D * noise(st, 31);
    m.chest.rotation.set(bodyRoll, pitch, yaw);
    m.pelvis.rotation.set(roll * hipShare * rollAt(S.phase + lead * (1 - sharp)), legPitch, -1.8 * yaw);
    m.pelvis.position.y = -0.36 * Math.sin(yaw);
    // Keep the waist joined to the pitched chest, then let the hips drop a little further.
    m.pelvis.position.x = -0.36 * Math.cos(pitch);
    // Keep only small pose variation here; the common body parent carries buoyancy and pull lift.
    const heave = 0.003 * noise(1.5 * st, 21);
    m.chest.position.z = heave + S.ride.height;
    m.pelvis.position.z = 0.36 * Math.sin(pitch) - (F.sinking ? 0.05 : 0)
      + 0.6 * heave + S.ride.height - S.ride.hips;
    // The head stays steady while the body rolls beneath it (the neck takes up half the roll),
    // then turns with the roll to breathe, one goggle staying in the water.
    const steady = -0.5 * bodyRoll, turn = Math.sign(breath) * 78 * D - bodyRoll;
    m.head.rotation.x = clamp(lerp(steady, turn, Math.abs(breath)), -70 * D, 70 * D) + 1.5 * D * noise(3 * st, 41);

    const right = arm(rushed(strokePhase(S.phase, P), P), P, F);
    const left = arm(rushed(strokePhase((S.phase + 0.5) % 1, P), P), P, F);
    vary(right, st, 1);
    vary(left, st + 0.5, 5);
    const slipness = smooth(clamp((0.75 * P.slip + 0.5 * (1 - P.catch) - 0.25) / 0.3, 0, 1));
    poseArm(m, 'R', right, P, slipness, bodyRoll, pitch);
    poseArm(m, 'L', left, P, slipness, bodyRoll, pitch);
    poseLegs(m, P, F, st);
    moveThroughWater(m, P, scaled, slipness, breath, previousX, resetMotion);

    const [eb, et, ec] = EMPHASIS[P.emphasis] || EMPHASIS.balanced;
    const k = P.intensity;
    const core = Math.abs(Math.sin(w * (S.phase - ROLL_PEAK + lead))) * (0.35 + 0.65 * P.drive) * (F.flathips ? 0.3 : 1);
    patch(m.backR, eb * k * right.back);
    patch(m.backL, eb * k * left.back);
    patch(m.triR, et * k * right.triceps);
    patch(m.triL, et * k * left.triceps);
    patch(m.core, ec * k * core);
    patch(m.hipR, ec * k * core);
    patch(m.hipL, ec * k * core);
    return [right, left, slipness];
  }

  function advance(scaled) {
    if (!S.params || !resolve()) return;
    const P = S.params, m = S.m;
    const previousOffset = S.offset;
    // Sample moving limbs at a bounded interval too, including the race's 4x playback.
    const steps = Math.max(1, Math.ceil(scaled * 120));
    let posed;
    for (let i = 0; i < steps; i++) posed = poseSwimmer(P, m, scaled / steps, S.trailReset && i === 0);
    const [right, left, slipness] = posed;
    if (scaled > 0) S.flow = (S.offset - previousOffset) / scaled;
    updateSplash(m, P, scaled, slipness);
    updateTrails(m, P, scaled);
    updateWater(m, P, scaled);
    fitView();
    // Buoys scroll back at swim speed and wrap around a 9 m window centred on the swimmer.
    const span = 9;
    m.buoys.forEach((b, i) => {
      b.position.x = wrap((m.basePos[i] - S.offset + 4.5) / span) * span - 4.5;
    });
    if (!externalClock) updateHud(right, left);
  }

  // Scrubbing the timeline seeks the right-arm phase directly.
  function bindTimeline() {
    let dragging = false;
    const pause = () => {
      const button = find('play', '.lc-play');
      if (S.params?.playing && !S.seekPausePending && button) {
        S.seekPausePending = true;
        button.click();
      }
    };
    const seekFrom = event => {
      if (!S.active) return;
      const bar = event.target.closest && event.target.closest('.lc-timeline');
      const node = bar || find('timeline', '.lc-timeline');
      if (!node) return;
      const rect = node.getBoundingClientRect();
      S.phase = wrap(clamp((event.clientX - rect.left) / rect.width, 0, 0.999));
      S.last = null;
      S.trailReset = true;
    };
    document.addEventListener('pointerdown', e => {
      if (!S.active) return;
      if (!e.target.closest || !e.target.closest('.lc-timeline')) return;
      pause();
      dragging = true;
      seekFrom(e);
    });
    document.addEventListener('pointermove', e => { if (dragging) seekFrom(e); });
    document.addEventListener('pointerup', () => { dragging = false; });
    document.addEventListener('pointercancel', () => { dragging = false; });
    document.addEventListener('keydown', e => {
      if (!S.active || !e.target.closest?.('.lc-timeline') || e.ctrlKey || e.metaKey || e.altKey) return;
      const step = {ArrowLeft: '.lc-step-back', ArrowDown: '.lc-step-back',
        ArrowRight: '.lc-step-forward', ArrowUp: '.lc-step-forward'}[e.key];
      if (!step && e.key !== 'Home' && e.key !== 'End') return;
      e.preventDefault();
      if (step) document.querySelector(root)?.querySelector(step)?.click();
      else {
        pause();
        S.phase = e.key === 'Home' ? 0 : 0.999;
        S.last = null; S.trailReset = true;
      }
    });
  }

  // Shortcuts click the matching buttons so Python stays the single owner of state.
  const SHORTCUTS = {
    ' ': '.lc-play', ArrowLeft: '.lc-step-back', ArrowRight: '.lc-step-forward', c: '.lc-reset-camera', v: '.lc-split-toggle', p: '.lc-pin-toggle', h: '.lc-dock-toggle',
  };
  function bindKeys() {
    document.addEventListener('keydown', e => {
      if (!S.active) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const focus = document.activeElement;
      if (focus && focus.closest && focus.closest('input, textarea, [role="slider"], [role="tab"], [role="combobox"], [contenteditable]')) return;
      // A focused button already handles Space natively.
      if (e.key === ' ' && focus && focus.closest && focus.closest('button')) return;
      const selector = /^[1-9]$/.test(e.key) ? `.lc-preset-${e.key}` : SHORTCUTS[e.key.length === 1 ? e.key.toLowerCase() : e.key];
      const button = selector && document.querySelector(root)?.querySelector(selector);
      if (!button) return;
      e.preventDefault();
      button.click();
    });
  }

  const faultFlags = params => Object.fromEntries((params.faults || []).map(key => [key, true]));

  // ---- public API (called from Python via BrowserEngine) ----------------------
  return {
    start(sceneId, ids, params) {
      S.sceneId = sceneId; S.ids = ids; S.params = params; S.faults = faultFlags(params);
      S.m = null; S.last = null; S.ui = {};
      if (!S.running) {
        S.running = true;
        if (!externalClock) requestAnimationFrame(frame);
        window.addEventListener('resize', () => setTimeout(fitCamera, 50));
        if (!externalClock) { bindTimeline(); bindKeys(); }
      }
    },
    set(params) {
      if (!params.playing) S.seekPausePending = false;
      if (!params.playing && params.speed !== S.params?.speed) S.ride = null;
      S.params = Object.assign({}, S.params, params); S.faults = faultFlags(S.params);
      if (S.m) for (const p of S.m.probes) p.known = false;
    },
    step(amount) { S.phase = wrap(S.phase + amount); S.last = null; S.trailReset = true; return S.phase; },
    fit() { setTimeout(fitCamera, 60); },
    setActive(active) { S.active = active; S.last = null; if (active) setTimeout(fitCamera, 60); },
    ready() { return resolve() && setupWater(S.m); },
    advance,
    reset() {
      S.phase = 0; S.cycles = 0; S.offset = 0; S.last = null; S.ride = null; S.trailReset = true;
      if (S.m?.pool) S.m.pool.time = 0;
      advance(0);
    },
    setView,
    resetCamera,
  };
};
window.LongCatch = window.LongCatch || window.createLongCatchEngine();
