// Long Catch browser animation engine.
//
// Python owns the settings and sends them through window.LongCatch.set();
// this loop owns the live cycle phase and poses the swimmer every frame.
// Configuration arrives as window.LONG_CATCH_CONFIG = {colors, background, phases, finish, arm}.
// Coordinates: head towards +x, z up, right side towards -y, water surface at z = 0.
window.LongCatch = window.LongCatch || (() => {
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
  function softReach(d) {
    if (d > MAX_REACH - SOFT) return MAX_REACH - SOFT * Math.exp(-(d - MAX_REACH + SOFT) / SOFT);
    if (d < MIN_REACH + SOFT) return MIN_REACH + SOFT * Math.exp(-(MIN_REACH + SOFT - d) / SOFT);
    return d;
  }

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
  function arm(p, P, F) {
    const c = P.catch, s = P.slip, L = P.length;
    const exit = P.exit, fin = CONFIG.finish;
    // Stroke depth: -1 keeps the hand tucked close to the body, +1 pulls deep with a straighter arm.
    const d = 2 * P.depth - 1;
    const midRec = exit + (1 - exit) * 0.4, lateRec = exit + (1 - exit) * 0.72;
    const over = F.overreach ? 1 : 0, cross = F.crossover ? 1 : 0;
    // Entry angle tilts the extended arm about the shoulder: 0 deg skims the surface, larger points to the floor.
    const tilt = deg => [0.56 * Math.cos(deg * D), -0.56 * Math.sin(deg * D)];
    const [enterX, enterH] = tilt(P.entry), [glideX, glideH] = tilt(P.entry + 3);
    const x = keyed(p, [
      [0, enterX + 0.08 * over], [0.12, glideX - 0.01 + 0.08 * over], [0.21, lerp(0.30, 0.40, c) + 0.08 * over],
      [0.30, lerp(0.10, 0.27, c) - 0.12 * s + 0.10 * over],
      [0.50, -0.04 - 0.08 * s], [fin, -0.29 - 0.05 * L], [exit, -lerp(0.34, 0.48, L)],
      [midRec, -0.10], [lateRec, 0.22], [1, enterX + 0.08 * over],
    ]);
    // A crossover hand enters past the head's centre line, then sweeps back out during the pull.
    const out = keyed(p, [
      [0, 0.025], [0.12, 0.035], [0.21, 0.06], [0.30, 0.12 + 0.04 * (1 - c)], [0.50, 0.12],
      [fin, 0.08], [exit, 0.10], [midRec, 0.30], [lateRec, 0.22], [1, 0.025],
    ]) - cross * keyed(p, [[0, 0.33], [0.12, 0.31], [0.30, 0.15], [0.50, 0.02], [exit, 0], [lateRec, 0.08], [1, 0.33]]);
    // Distance-style catch: the hand tips down in front while the elbow stays high, then hangs
    // under the elbow so the forearm and hand form one near-vertical paddle facing backwards.
    const height = keyed(p, [
      [0, enterH + 0.03 * over], [0.12, glideH + 0.05 * over], [0.21, lerp(-0.16, -0.22, c) + 0.03 * over],
      [0.30, lerp(-0.26, -0.40, c) - 0.05 * d],
      [0.50, -0.37 - 0.09 * d], [fin, -0.26 - 0.05 * d], [exit, 0.0], [midRec, 0.12], [lateRec, 0.12],
      [1, enterH + 0.03 * over],
    ]);
    // Recovery is elbow-led: the elbow arcs highest while the relaxed hand swings below and outside it.
    const elbow = [
      keyed(p, [[exit, -0.22], [midRec, -0.04], [lateRec, 0.14], [1, 0.26]]),
      keyed(p, [[exit, 0.18], [midRec, 0.26], [lateRec, 0.22], [1, 0.08]]),
      keyed(p, [[exit, 0.20], [midRec, 0.40], [lateRec, 0.32], [1, 0.05]]),
    ];
    const recovery = p < exit ? 0 : smooth(clamp((p - exit) / 0.05, 0, 1)) * smooth(clamp((1 - p) / 0.07, 0, 1));
    const under = p < exit;
    // Over-extension: locked arm, shrugged shoulder, and a "stop sign" wrist that brakes at the front.
    const front = over * keyed(p, [[0, 1], [0.16, 1], [0.30, 0], [0.92, 0], [1, 1]]);
    const wrist = (under ? -48 * s * bump(p, 0.08, exit) + 12 * (1 - s) * bump(p, 0.12, 0.45) : 15) - 32 * front;
    const stage = p < 0.12 ? 0 : p < 0.30 ? 1 : p < fin ? 2 : p < exit ? 3 : 4;
    // Through the catch the upper arm rotates inward: the elbow guide swings forward and out
    // (dipping slightly from straight up), so a good catch keeps the elbow ahead of the hand.
    const catching = bump(p, 0.14, 0.46);
    const pole = lerp(-0.35, 1, c) - 0.25 * catching;
    return {
      x, out, height, elbow, recovery, pole, lead: 0.7 * c * catching, shrug: front,
      wrist: wrist * D, under, stage,
      back: bump(p, 0.10, fin + 0.02), triceps: bump(p, fin - 0.12, exit + 0.04),
    };
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
    const aspect = el.$el.clientWidth / Math.max(1, el.$el.clientHeight);
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
  import('nicegui-scene').then(mod => { THREE = mod.THREE; }).catch(() => {});
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
        const drift = P.speed * dt;
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
  function drawEdgeFade(g, n) {
    g.fillStyle = '#fff';
    g.fillRect(0, 0, n, n);
    g.globalCompositeOperation = 'multiply';
    for (const [x1, y1] of [[n, 0], [0, n]]) {
      const grad = g.createLinearGradient(0, 0, x1, y1);
      grad.addColorStop(0, '#000');
      grad.addColorStop(0.22, '#fff');
      grad.addColorStop(0.78, '#fff');
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
    const old = scene.getObjectByName('lc-pool');
    if (old) scene.remove(old);

    m.water.geometry.dispose();
    m.water.geometry = new THREE.PlaneGeometry(SURFACE.w, SURFACE.h, SURFACE.nx, SURFACE.ny);
    m.water.material = new THREE.MeshPhongMaterial({
      color: CONFIG.colors.water, specular: 0x6fa9b8, shininess: 90, transparent: true, opacity: 0.17,
      side: THREE.DoubleSide, depthWrite: false, alphaMap: edge, map: flow,
    });
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
    m.pool = { tiles, caustics, flow, time: 0 };
    return true;
  }

  // Move the swell, bow wave, wake, kick wash, and splash ripples, and scroll the floor back at
  // swim speed (so the pool slides past).
  function updateWater(m, P, dt) {
    if (!setupWater(m)) return;
    const pool = m.pool, t = (pool.time += dt), off = S.offset, fx = m.fx;
    const pos = m.water.geometry.attributes.position, a = pos.array;
    const pace = Math.min(1, P.speed), ripples = fx ? fx.ripples : [], wash = fx ? fx.wash : 0, footX = fx ? fx.footX : -1.6;
    for (let i = 0; i < pos.count; i++) {
      const x = a[3 * i] + SURFACE.x + off, y = a[3 * i + 1], lx = a[3 * i] + SURFACE.x;
      const swell = 0.009 * Math.sin(2.1 * x + 1.3 * y + 1.7 * t) + 0.006 * Math.sin(3.4 * x - 2.2 * y + 2.6 * t)
        + 0.003 * Math.sin(7.9 * x + 5.1 * y + 4.1 * t);
      // Bow wave lifts the water at the head; a shallow trough follows at the shoulders.
      const bow = 0.018 * Math.exp(-((lx - 0.62) ** 2) / 0.02 - y * y / 0.03)
        - 0.012 * Math.exp(-((lx - 0.3) ** 2) / 0.03 - y * y / 0.09);
      let h = swell + bow * pace;
      // Kelvin-style V wake: crests spread back from the head at about 20° and hold still relative to
      // the swimmer, fading with distance.
      const d = 0.55 - lx;
      if (d > 0) {
        const wing = Math.abs(y) - 0.36 * d, width = 0.05 + 0.04 * d;
        h += 0.006 * pace * Math.exp(-d / 2.4 - (wing * wing) / (width * width)) * Math.cos(12 * d);
      }
      // Kick wash: choppy water over and behind the feet that is carried back with the water.
      const behind = footX + 0.15 - lx;
      if (wash > 0.001 && behind > 0 && behind < 2) {
        const spread = 0.12 + 0.12 * behind;
        h += 0.007 * wash * Math.exp(-behind / 0.7 - (y * y) / (spread * spread))
          * Math.sin(17 * x + 9 * t) * Math.sin(13 * y - 6 * t);
      }
      // Ring ripples travel out from each splash and lose height as they spread and age.
      for (const [rx, ry, age, s] of ripples) {
        const front = FX.rippleSpeed * age + 0.03, gap = Math.hypot(lx - rx, y - ry) - front;
        if (gap > 0.3 || gap < -0.3) continue;
        h += (s * Math.exp(-1.8 * age - (gap * gap) / 0.012) * Math.cos(20 * gap)) / (1 + 4 * front);
      }
      a[3 * i + 2] = h;
    }
    pos.needsUpdate = true;
    m.water.geometry.computeVertexNormals();
    pool.tiles.offset.x = wrap(off);
    // Positive UV offset moves the streaks back across the swimmer-relative surface.
    pool.flow.offset.x = wrap(off * pool.flow.repeat.x / SURFACE.w);
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
  const FX = { maxRipples: 24, maxBubbles: 420, maxSpray: 160, rippleSpeed: 0.55, gravity: 9.81, rise: 0.28 };
  const rand = (a, b) => a + (b - a) * Math.random();
  const spawnCount = rate => Math.floor(rate + Math.random());

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
    return { max, list: [], geo, pos, col, color };
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
      limbs: ALL_LIMBS.map(limb => ({
        limb, hand: limb.key.startsWith('hand'), known: false, air: 0, wet: 0,
        pos: new THREE.Vector3(), prev: new THREE.Vector3(), vel: new THREE.Vector3(),
      })),
    };
    return m.fx;
  }

  function emit(sys, x, y, z, vx, vy, vz, life) {
    if (sys.list.length < sys.max) sys.list.push([x, y, z, vx, vy, vz, 0, life]);
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
    const fx = setupSplash(m), flow = P.speed;
    if (S.trailReset) {
      fx.ripples.length = fx.bubbles.list.length = fx.spray.list.length = 0;
      fx.wash = 0;
      for (const l of fx.limbs) { l.known = false; l.air = l.wet = 0; }
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
      stepFx(fx, flow, dt);
    }
    drawParticles(fx.bubbles, 0.7);
    drawParticles(fx.spray, 0.9);
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
    const cos = Math.cos(bodyRoll), sin = Math.sin(bodyRoll), lateral = sgn * 0.8;
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    sh.position.x = r.baseX + 0.04 * a.shrug;
    // Convert a shoulder-relative point with a world height into the rolled (then pitched) chest frame.
    const chestZ = (height, out, x) =>
      ((height + 0.06 + (sh.position.x + x) * sp) / cp - sin * (sh.position.y + sgn * out)) / cos;
    r.target.set(a.x, sgn * a.out, chestZ(a.height, a.out, a.x));
    const reach = softReach(r.target.length());
    r.axis.copy(r.target).normalize();
    r.target.copy(r.axis).multiplyScalar(reach);
    // Keep the elbow guide world-up when the chest rolls underneath the arm.
    r.pole.set(lerp(-0.15, 0.35, P.catch) + a.lead, lateral * cos + a.pole * sin, -lateral * sin + a.pole * cos);
    r.pole.addScaledVector(r.axis, -r.pole.dot(r.axis)).normalize();
    if (a.recovery > 0) {
      const [ex, eo, eh] = a.elbow;
      r.hint.set(ex, sgn * eo, chestZ(eh, eo, ex));
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
      r.normal.copy(r.pole).addScaledVector(r.z, -outward);
      // With the guide nearly all inward, its remainder can flip fore/aft; bias it to the back side.
      const spare = r.normal.length();
      if (spare < 0.35) {
        r.hint.set(0, 0, 1).addScaledVector(r.axis, -r.axis.z);
        r.hint.addScaledVector(r.z, -r.hint.dot(r.z)).normalize();
        r.normal.addScaledVector(r.hint, 0.35 - spare);
      }
      r.normal.normalize();
      r.pole.copy(r.z).multiplyScalar(minOut).addScaledVector(r.normal, Math.sqrt(1 - minOut ** 2));
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
    m['wr' + side].rotation.set(0, a.wrist, 0);
    paint(m['fa' + side], a.under, slipness);
    paint(m['ha' + side], a.under, slipness);
    paint(m['thumb' + side], a.under, slipness);
  }

  // Healthy flutter drives from the hips; a knee kick drops the thighs and bends the knees hard.
  // Each beat varies a little in size and timing (t is stroke time; zero kick stays still).
  function poseLegs(m, P, F, t) {
    const kick = 2 * Math.PI * 3 * S.phase;
    const knees = F.kneekick ? 1 : 0, base = knees ? Math.max(P.kick, 0.6) : P.kick;
    for (const [side, offset] of [['R', 0], ['L', Math.PI]]) {
      const k = base * (1 + 0.12 * noise(3 * t, offset ? 52 : 51));
      const angle = kick + offset + 0.15 * noise(2 * t, offset ? 62 : 61);
      const hip = knees ? -0.12 * k + 0.06 * k * Math.sin(angle) : 0.26 * k * Math.sin(angle);
      const knee = knees ? 0.2 + 1.3 * k * Math.max(0, Math.sin(angle - 0.3)) : 0.45 * k * Math.max(0, Math.sin(angle - 0.7));
      m['leg' + side].rotation.set(0, hip, 0);
      m['knee' + side].rotation.set(0, knee, 0);
      m['ankle' + side].rotation.set(0, -0.12 + k * (knees ? 0.25 : 0.10) * Math.sin(angle - 0.5), 0);
    }
  }

  // ---- HUD and input ----------------------------------------------------------

  // DOM lookups are cached and writes skipped when unchanged to keep frames cheap.
  function find(key, selector) {
    const cached = S.ui[key];
    if (cached && cached.isConnected) return cached;
    S.ui[key] = document.querySelector(selector);
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
  }

  // ---- frame loop -------------------------------------------------------------

  // Advance the phase, then pose body, arms, legs, overlays, trails, and lane ropes.
  function frame(t) {
    requestAnimationFrame(frame);
    if (document.hidden || !S.params) { S.last = null; return; }
    const dt = S.last === null ? 0 : Math.min(0.1, (t - S.last) / 1000);
    S.last = t;
    if (!resolve()) return;
    const P = S.params, m = S.m;
    const scaled = P.playing ? dt * (P.playback || 1) : 0;
    if (P.playing) {
      const next = S.phase + scaled / (120 / P.rate);
      if (next >= 1) S.cycles++;
      S.phase = next % 1;
      S.offset += P.speed * scaled;
    }
    // Body roll: positive = right shoulder down, deepest at the right catch. Connected drive lets the hips lead.
    // Flat hips moves the rotation into the shoulders; sinking legs pitches the chest up and the pelvis down.
    // Breathing deepens the roll a few degrees toward the breathing side; roll size also wanders slightly.
    const F = S.faults, w = 2 * Math.PI, st = S.cycles + S.phase, breath = breathing(P);
    const chestGain = F.overrotation ? 1.65 : F.flathips ? 1.25 : 1;
    const roll = Math.min(80, P.roll * chestGain * (1 + 0.04 * noise(2 * st, 11))) * D;
    const lead = 0.07 * P.drive - 0.05 * (1 - P.drive);
    const hipShare = F.flathips ? 0.06 : F.overrotation ? 0.85 : 0.3 + 0.6 * P.drive;
    const bodyRoll = roll * Math.cos(w * (S.phase - ROLL_PEAK)) + 6 * D * breath;
    const pitch = F.sinking ? -14 * D : 0, legPitch = F.sinking ? -24 * D : 0;
    // Snaking: the chest yaws with each sweep and the hips swing the other way behind it.
    const yaw = (F.snaking ? 7 * D * Math.sin(w * (S.phase - ROLL_PEAK)) : 0) + 0.8 * D * noise(st, 31);
    m.chest.rotation.set(bodyRoll, pitch, yaw);
    m.pelvis.rotation.set(roll * hipShare * Math.cos(w * (S.phase - ROLL_PEAK + lead)), legPitch, -1.8 * yaw);
    m.pelvis.position.y = -0.36 * Math.sin(yaw);
    // Keep the waist joined to the pitched chest, then let the hips drop a little further.
    m.pelvis.position.x = -0.36 * Math.cos(pitch);
    // The body rides a little higher as each arm presses back (twice per cycle), with a slight drift.
    const heave = 0.008 * Math.cos(2 * w * (S.phase - 0.4)) + 0.004 * noise(1.5 * st, 21);
    m.chest.position.z = heave;
    m.pelvis.position.z = 0.36 * Math.sin(pitch) - (F.sinking ? 0.05 : 0) + 0.6 * heave;
    // The head stays steady while the body rolls beneath it (the neck takes up half the roll),
    // then turns with the roll to breathe, one goggle staying in the water.
    const steady = -0.5 * bodyRoll, turn = Math.sign(breath) * 78 * D - bodyRoll;
    m.head.rotation.x = clamp(lerp(steady, turn, Math.abs(breath)), -70 * D, 70 * D) + 1.5 * D * noise(3 * st, 41);

    const right = arm(rushed(S.phase, P), P, F), left = arm(rushed((S.phase + 0.5) % 1, P), P, F);
    vary(right, st, 1);
    vary(left, st + 0.5, 5);
    const slipness = smooth(clamp((0.75 * P.slip + 0.5 * (1 - P.catch) - 0.25) / 0.3, 0, 1));
    poseArm(m, 'R', right, P, slipness, bodyRoll, pitch);
    poseArm(m, 'L', left, P, slipness, bodyRoll, pitch);
    poseLegs(m, P, F, st);
    updateSplash(m, P, scaled, slipness);
    updateTrails(m, P, scaled);
    updateWater(m, P, scaled);
    fitView();

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

    // Buoys scroll back at swim speed and wrap around a 9 m window centred on the swimmer.
    const span = 9;
    m.buoys.forEach((b, i) => {
      b.position.x = wrap((m.basePos[i] - S.offset + 4.5) / span) * span - 4.5;
    });
    updateHud(right, left);
  }

  // Scrubbing the timeline seeks the right-arm phase directly.
  function bindTimeline() {
    let dragging = false;
    const seekFrom = event => {
      const bar = event.target.closest && event.target.closest('.lc-timeline');
      const node = bar || find('timeline', '.lc-timeline');
      if (!node) return;
      const rect = node.getBoundingClientRect();
      S.phase = wrap(clamp((event.clientX - rect.left) / rect.width, 0, 0.999));
      S.last = null;
      S.trailReset = true;
    };
    document.addEventListener('pointerdown', e => {
      if (!e.target.closest || !e.target.closest('.lc-timeline')) return;
      dragging = true;
      seekFrom(e);
    });
    document.addEventListener('pointermove', e => { if (dragging) seekFrom(e); });
    document.addEventListener('pointerup', () => { dragging = false; });
  }

  // Shortcuts click the matching buttons so Python stays the single owner of state.
  const SHORTCUTS = {
    ' ': '.lc-play', ArrowLeft: '.lc-step-back', ArrowRight: '.lc-step-forward', c: '.lc-reset-camera', v: '.lc-split-toggle',
  };
  function bindKeys() {
    document.addEventListener('keydown', e => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const focus = document.activeElement;
      if (focus && focus.closest && focus.closest('input, textarea, [role="slider"], [contenteditable]')) return;
      // A focused button already handles Space natively.
      if (e.key === ' ' && focus && focus.closest && focus.closest('button')) return;
      const selector = /^[1-9]$/.test(e.key) ? `.lc-preset-${e.key}` : SHORTCUTS[e.key.length === 1 ? e.key.toLowerCase() : e.key];
      const button = selector && document.querySelector(selector);
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
        requestAnimationFrame(frame);
        window.addEventListener('resize', () => setTimeout(fitCamera, 50));
        bindTimeline();
        bindKeys();
      }
    },
    set(params) { S.params = Object.assign({}, S.params, params); S.faults = faultFlags(S.params); },
    step(amount) { S.phase = wrap(S.phase + amount); S.last = null; S.trailReset = true; return S.phase; },
    fit() { setTimeout(fitCamera, 60); },
    setView,
    resetCamera,
  };
})();
