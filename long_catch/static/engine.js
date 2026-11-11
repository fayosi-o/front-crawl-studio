// Long Catch browser animation engine.
// Python owns the settings; this loop owns the live cycle phase and the pose.
// Configuration arrives as window.LONG_CATCH_CONFIG = {colors, phases, arm}.
window.LongCatch = window.LongCatch || (() => {
  const CONFIG = window.LONG_CATCH_CONFIG;
  const S = { sceneId: null, ids: null, params: null, faults: {}, phase: 0, offset: 0, last: null, m: null, running: false, ui: {} };
  const D = Math.PI / 180;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = t => t * t * (3 - 2 * t);
  const wrap = p => ((p % 1) + 1) % 1;
  const bump = (p, a, b) => (p > a && p < b ? Math.sin(Math.PI * (p - a) / (b - a)) : 0);
  const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  const C = { hold: rgb(CONFIG.colors.hold), slip: rgb(CONFIG.colors.slip), skin: rgb(CONFIG.colors.skin) };
  const EMPHASIS = { back: [1, 0, 0], triceps: [0, 1, 0], core: [0, 0, 1], balanced: [0.55, 0.55, 0.55] };
  const PHASES = CONFIG.phases;
  const [UPPER, FOREARM] = CONFIG.arm;
  const reachAt = bend => Math.sqrt(UPPER ** 2 + FOREARM ** 2 + 2 * UPPER * FOREARM * Math.cos(bend * D));
  const MIN_REACH = reachAt(145);
  const MAX_REACH = reachAt(8);
  const ROLL_PEAK = 0.18;
  // Ease into the reach limits so the elbow straightens or folds gradually instead of snapping.
  const SOFT = 0.045;
  function softReach(d) {
    if (d > MAX_REACH - SOFT) return MAX_REACH - SOFT * Math.exp(-(d - MAX_REACH + SOFT) / SOFT);
    if (d < MIN_REACH + SOFT) return MIN_REACH + SOFT * Math.exp(-(MIN_REACH + SOFT - d) / SOFT);
    return d;
  }

  function keyed(p, keys) {
    for (let i = 0; i < keys.length - 1; i++) {
      const [p0, v0] = keys[i], [p1, v1] = keys[i + 1];
      if (p <= p1) return lerp(v0, v1, smooth(clamp((p - p0) / (p1 - p0), 0, 1)));
    }
    return keys[keys.length - 1][1];
  }

  // Wrist target path for one arm at phase p, plus overlay and colouring values.
  // F holds active stroke faults; each one bends the healthy path toward a typical error.
  function arm(p, P, F) {
    const c = P.catch, s = P.slip, L = P.length;
    const exit = P.exit;
    const midRec = exit + (1 - exit) * 0.4, lateRec = exit + (1 - exit) * 0.72;
    const over = F.overreach ? 1 : 0, cross = F.crossover ? 1 : 0;
    const x = keyed(p, [
      [0, 0.56 + 0.08 * over], [0.12, 0.55 + 0.08 * over], [0.30, lerp(0.10, 0.30, c) - 0.12 * s + 0.10 * over],
      [0.48, -0.04 - 0.08 * s], [0.62, -0.29 - 0.05 * L], [exit, -lerp(0.34, 0.48, L)],
      [midRec, -0.10], [lateRec, 0.22], [1, 0.56 + 0.08 * over],
    ]);
    // A crossover hand enters past the head's centre line, then sweeps back out during the pull.
    const out = keyed(p, [
      [0, 0.025], [0.12, 0.035], [0.30, 0.07 + 0.08 * (1 - c)], [0.48, 0.10],
      [0.62, 0.08], [exit, 0.10], [midRec, 0.30], [lateRec, 0.22], [1, 0.025],
    ]) - cross * keyed(p, [[0, 0.33], [0.12, 0.31], [0.30, 0.15], [0.48, 0.02], [exit, 0], [lateRec, 0.08], [1, 0.33]]);
    // Mid-pull hand sits about a forearm below the shoulder, so the elbow stays bent near 90-110 deg.
    const height = keyed(p, [
      [0, -0.045 + 0.03 * over], [0.12, -0.07 + 0.05 * over], [0.30, lerp(-0.26, -0.32, c)], [0.48, -0.37],
      [0.62, -0.26], [exit, 0.0], [midRec, 0.12], [lateRec, 0.12], [1, -0.045 + 0.03 * over],
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
    const stage = p < 0.12 ? 0 : p < 0.30 ? 1 : p < 0.62 ? 2 : p < exit ? 3 : 4;
    return {
      x, out, height, elbow, recovery, pole: lerp(-0.35, 1, c), shrug: front,
      wrist: wrist * D, under, stage,
      back: bump(p, 0.10, 0.64), triceps: bump(p, 0.50, exit + 0.04),
    };
  }

  // Spinning arms race through the underwater part, leaving more of the cycle for recovery.
  function rushed(p, P) {
    if (P.rush >= 1) return p;
    const exit = P.exit, early = exit * P.rush;
    return p < early ? p * exit / early : exit + (p - early) * (1 - exit) / (1 - early);
  }

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

  function resetCamera() {
    if (!S.el || !S.home) return;
    S.el.camera.position.copy(S.home.position);
    S.el.controls.target.copy(S.home.target);
    fitCamera();
  }

  function paint(mesh, under, slipness) {
    const col = under ? C.hold.map((v, i) => lerp(v, C.slip[i], slipness)) : C.skin;
    mesh.material.color.setRGB(col[0], col[1], col[2]);
  }

  function patch(mesh, value) {
    mesh.material.opacity = clamp(Math.sqrt(Math.max(0, value)) * 0.85, 0, 0.85);
    mesh.visible = value > 0.02;
  }

  // Fixed-length two-bone inverse kinematics for one arm in the rolled chest frame.
  function poseArm(m, side, a, P, slipness, bodyRoll) {
    const sgn = side === 'R' ? -1 : 1, sh = m['sh' + side], r = m.rigs[side];
    const cos = Math.cos(bodyRoll), sin = Math.sin(bodyRoll), lateral = sgn * 0.8;
    sh.position.x = r.baseX + 0.04 * a.shrug;
    // Convert a shoulder-relative point with a world height into the rolled chest frame.
    const chestZ = (height, out) => (height + 0.06 - sin * (sh.position.y + sgn * out)) / cos;
    r.target.set(a.x, sgn * a.out, chestZ(a.height, a.out));
    const reach = softReach(r.target.length());
    r.axis.copy(r.target).normalize();
    r.target.copy(r.axis).multiplyScalar(reach);
    // Keep the elbow guide world-up when the chest rolls underneath the arm.
    r.pole.set(lerp(-0.15, 0.35, P.catch), lateral * cos + a.pole * sin, -lateral * sin + a.pole * cos);
    r.pole.addScaledVector(r.axis, -r.pole.dot(r.axis)).normalize();
    if (a.recovery > 0) {
      const [ex, eo, eh] = a.elbow;
      r.hint.set(ex, sgn * eo, chestZ(eh, eo));
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
  function poseLegs(m, P, F) {
    const kick = 2 * Math.PI * 3 * S.phase;
    const knees = F.kneekick ? 1 : 0, k = knees ? Math.max(P.kick, 0.6) : P.kick;
    for (const [side, offset] of [['R', 0], ['L', Math.PI]]) {
      const angle = kick + offset;
      const hip = knees ? -0.12 * k + 0.06 * k * Math.sin(angle) : 0.26 * k * Math.sin(angle);
      const knee = knees ? 0.2 + 1.3 * k * Math.max(0, Math.sin(angle - 0.3)) : 0.45 * k * Math.max(0, Math.sin(angle - 0.7));
      m['leg' + side].rotation.set(0, hip, 0);
      m['knee' + side].rotation.set(0, knee, 0);
      m['ankle' + side].rotation.set(0, -0.12 + k * (knees ? 0.25 : 0.10) * Math.sin(angle - 0.5), 0);
    }
  }

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

  function frame(t) {
    requestAnimationFrame(frame);
    if (document.hidden || !S.params) { S.last = null; return; }
    const dt = S.last === null ? 0 : Math.min(0.1, (t - S.last) / 1000);
    S.last = t;
    if (!resolve()) return;
    const P = S.params, m = S.m;
    if (P.playing) {
      const scaled = dt * (P.playback || 1);
      S.phase = (S.phase + scaled / (120 / P.rate)) % 1;
      S.offset += P.speed * scaled;
    }
    // Body roll: positive = right shoulder down, deepest at the right catch. Connected drive lets the hips lead.
    const F = S.faults, w = 2 * Math.PI;
    const roll = (F.overrotation ? Math.min(80, P.roll * 1.65) : P.roll) * D;
    const lead = 0.07 * P.drive - 0.05 * (1 - P.drive);
    const hipShare = F.overrotation ? 0.85 : 0.3 + 0.6 * P.drive;
    const bodyRoll = roll * Math.cos(w * (S.phase - ROLL_PEAK));
    // Snaking: the chest yaws with each sweep and the hips swing the other way behind it.
    const yaw = F.snaking ? 7 * D * Math.sin(w * (S.phase - ROLL_PEAK)) : 0;
    m.chest.rotation.set(bodyRoll, 0, yaw);
    m.pelvis.rotation.set(roll * hipShare * Math.cos(w * (S.phase - ROLL_PEAK + lead)), 0, -1.8 * yaw);
    m.pelvis.position.y = -0.36 * Math.sin(yaw);

    const right = arm(rushed(S.phase, P), P, F), left = arm(rushed((S.phase + 0.5) % 1, P), P, F);
    const slipness = smooth(clamp((0.75 * P.slip + 0.5 * (1 - P.catch) - 0.25) / 0.3, 0, 1));
    poseArm(m, 'R', right, P, slipness, bodyRoll);
    poseArm(m, 'L', left, P, slipness, bodyRoll);
    poseLegs(m, P, F);

    const [eb, et, ec] = EMPHASIS[P.emphasis] || EMPHASIS.balanced;
    const k = P.intensity;
    const core = Math.abs(Math.sin(w * (S.phase - ROLL_PEAK + lead))) * (0.35 + 0.65 * P.drive);
    patch(m.backR, eb * k * right.back);
    patch(m.backL, eb * k * left.back);
    patch(m.triR, et * k * right.triceps);
    patch(m.triL, et * k * left.triceps);
    patch(m.core, ec * k * core);
    patch(m.hipR, ec * k * core);
    patch(m.hipL, ec * k * core);

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
  const SHORTCUTS = { ' ': '.lc-play', ArrowLeft: '.lc-step-back', ArrowRight: '.lc-step-forward', c: '.lc-reset-camera' };
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
    step(amount) { S.phase = wrap(S.phase + amount); S.last = null; return S.phase; },
    resetCamera,
  };
})();
