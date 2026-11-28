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

  // A smooth curve through keyframes [[phase, value], ...] that keeps moving through each key instead
  // of easing to a stop at it, as `keyed` does. A monotone cubic (harmonic-mean slopes) never
  // overshoots a key, so a hand kept above the water stays above it. It starts and ends at rest, and
  // a key where the value turns back (a peak) is passed at rest in that coordinate only.
  function flowing(p, keys) {
    const n = keys.length;
    if (p <= keys[0][0]) return keys[0][1];
    if (p >= keys[n - 1][0]) return keys[n - 1][1];
    let i = 0;
    while (p > keys[i + 1][0]) i++;
    const slope = j => (keys[j + 1][1] - keys[j][1]) / (keys[j + 1][0] - keys[j][0]);
    const tangent = j => {
      if (j === 0 || j === n - 1) return 0;
      const a = slope(j - 1), b = slope(j);
      return a * b > 0 ? 2 * a * b / (a + b) : 0;
    };
    const [p0, v0] = keys[i], [p1, v1] = keys[i + 1], h = p1 - p0, t = (p - p0) / h, t2 = t * t, t3 = t2 * t;
    return (2 * t3 - 3 * t2 + 1) * v0 + (t3 - 2 * t2 + t) * h * tangent(i)
      + (3 * t2 - 2 * t3) * v1 + (t3 - t2) * h * tangent(i + 1);
  }
  const flowingVector = (p, keys) => [0, 1, 2].map(i => flowing(p, keys.map(([q, v]) => [q, v[i]])));

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
    // Early exit lifts the hand out at the waist (Python moves P.exit forward); a dropped elbow
    // sinks below the hand at the catch so the palm presses down instead of back.
    // Wrist press (the fix) lifts the palm back up and removes most of that sag; Shoulder reach pushes the
    // shoulder and the hand forward through the glide.
    // Hip finish carries the push right back to the hip before the hand leaves the water.
    const press = F.wristpress ? 1 : 0, rch = F.shoulderreach ? 1 : 0, hip = F.hipfinish ? 1 : 0;
    const early = F.earlyexit ? 1 : 0, sag = F.droppedelbow ? 1 - 0.7 * press : 0;
    const reachX = 0.08 * over + 0.05 * rch;
    // Entry angle tilts the extended arm about the shoulder: 0 deg skims the surface, larger points to the floor.
    const tilt = deg => [0.56 * Math.cos(deg * D), -0.56 * Math.sin(deg * D)];
    const [enterX, enterH] = tilt(P.entry), [glideX, glideH] = tilt(P.entry + 3);
    // Fingertips go in just past the head with the elbow still bent and high, then the arm extends
    // forward under the surface. An over-reaching swimmer spears in at full stretch instead.
    const entryX = lerp(0.36, enterX + 0.08, over) + 0.05 * rch, entryH = lerp(-0.01, enterH + 0.03, over);
    const pullX = lerp(0.10, 0.27, c) - 0.12 * s + 0.10 * over + 0.04 * rch;
    // The release sweeps the hand back, up and out past the thigh, so it leaves the water moving.
    const finishX = -lerp(0.40, 0.50, L) + 0.16 * early - 0.04 * hip;
    const exitX = -lerp(0.45, 0.55, L) + 0.16 * early - 0.04 * hip;
    // From the deepest point of the push to the arm's full extension in front the hand follows flowing
    // curves (see `flowing`; phases past 1 belong to the next cycle), so it never pauses at a
    // keyframe: it rises and turns out past the hip as the push ends, comes out of the water still
    // moving, and over the water the elbow leads: the relaxed hand trails behind it at first, then the
    // forearm swings forward past the head.
    const REACHED = 0.11, ahead = p < REACHED ? p + 1 : p, from = start => p >= start || p < REACHED;
    const lift = rec(0.15);
    let x = from(fin) ? flowing(ahead, [
      [fin, finishX], [exit, exitX], [lift, exitX + 0.09], [midRec, -0.17], [lateRec, 0.12],
      [preEntry, 0.30], [1, entryX], [1 + REACHED, enterX + reachX],
    ]) : flowing(p, [
      // One uninterrupted sweep from the catch through the pull to the hip. The hand keeps drifting back
      // as the pull begins (it never stops at the keyframe), then speeds up through the push; the
      // slight timing bias puts peak rearward speed in the push, not at a stop under the shoulder.
      [REACHED, enterX + reachX], [0.16, glideX - 0.01 + reachX], [0.22, lerp(0.30, 0.40, c) + reachX],
      ...[pull, 0.40, push, 0.58, fin].map(q => [q, lerp(pullX, finishX, smooth(((q - pull) / (fin - pull)) ** 1.25))]),
    ]);
    // Pull width: a narrow pull sweeps the hand in under the chest while the elbow stays out (the
    // "power diamond" of the hand, forearm, and upper arm); a wide one keeps the hand outside the
    // shoulder line with a straighter arm. Both open slightly out at the catch first.
    // A crossover hand enters past the head's centre line, then sweeps back out during the pull.
    // Over the water the hand swings out wide of the shoulder, under the elbow, and back in to enter
    // in line with the shoulder.
    const out = (from(push) ? flowing(ahead, [
      [push, lerp(-0.13, 0.11, w)], [fin, lerp(-0.06, 0.09, w)], [exit, lerp(0.05, 0.13, w)], [lift, 0.13],
      [midRec, 0.30], [lateRec, 0.26], [preEntry, 0.09], [1, 0.02], [1 + REACHED, 0.03],
    ]) : keyed(p, [
      [REACHED, 0.03], [0.16, 0.04], [0.22, 0.05 + 0.05 * w + 0.03 * (1 - c)],
      [0.36, lerp(-0.15, 0.12, w)], [push, lerp(-0.13, 0.11, w)],
    ])) - cross * keyed(p, [
      [0, 0.33], [0.16, 0.31], [0.30, 0.15], [push, 0.02], [exit, 0], [lateRec, 0.08], [preEntry, 0.24], [1, 0.33],
    ]);
    // Distance-style catch: the hand tips down in front while the elbow stays high, then hangs
    // under the elbow so the forearm and hand form one near-vertical paddle facing backwards.
    // Over the water the wrist stays low, so the relaxed hand hanging from it skims the surface.
    const height = from(push) ? flowing(ahead, [
      [push, -0.32 - 0.08 * d], [fin, -0.08 - 0.02 * d], [exit, 0.02], [lift, 0.07], [midRec, 0.08],
      [lateRec, 0.08], [preEntry, 0.05], [1, entryH], [1 + REACHED, enterH + 0.03 * over],
    ]) : keyed(p, [
      [REACHED, enterH + 0.03 * over], [0.16, glideH + 0.05 * over],
      [0.22, lerp(-0.16, -0.22, c) + 0.03 * over + 0.04 * sag],
      [0.30, lerp(-0.26, -0.40, c) - 0.05 * d + 0.04 * sag],
      [push, -0.32 - 0.08 * d],
    ]);
    // Push path: Pressing down sinks the hand toward the floor through the push; a Parallel push cancels
    // the hand's natural rise so it drives back level, coming up only as the push ends; a Late upsweep
    // adds an extra flick up at the last moment.
    const lvl = p > push && p < exit ? smooth(clamp((p - push) / 0.08, 0, 1))
      * (1 - smooth(clamp((p - (fin - 0.06)) / (exit - fin + 0.06), 0, 1))) : 0;
    const dy = -0.16 * (F.pushdown ? 1 : 0) * bump(p, 0.40, exit) - 0.22 * (F.flatpush ? 1 : 0) * lvl
      + 0.10 * (F.upsweep ? 1 : 0) * bump(p, fin - 0.05, exit + 0.02);
    // Recovery is elbow-led and relaxed: the elbow lifts up and out to the side (not straight up)
    // while the forearm hangs loosely beneath it, bent about square, then swings forward past the head.
    // Arm recovery: a low, relaxed arm keeps the elbow nearer the surface and a little lower out to the side.
    const lowArm = P.lowarm ?? 0, up = 1 - 0.6 * lowArm, side = 1 - 0.2 * lowArm;
    const elbow = flowingVector(p, [
      [exit, [-0.24, 0.12, 0.16]], [lift, [-0.18, 0.20 * side, 0.30 * up]], [midRec, [-0.06, 0.34 * side, 0.22 * up]],
      [lateRec, [0.08, 0.32 * side, 0.19 * up]],
      [preEntry, [0.14, 0.20 * side, 0.15 * up]], [1, [0.16, 0.10, 0.10]],
    ]);
    const recovery = p < exit ? 0 : smooth(clamp((p - exit) / 0.05, 0, 1)) * smooth(clamp((1 - p) / 0.07, 0, 1));
    const under = p < exit;
    // Underwater elbow direction. The upper arm rotates inward through the catch so the elbow
    // points out and up and stays ahead of the hand; a weak catch lets it drop and trail.
    // Narrow pulls flare the elbow out to the side; wide pulls point it back and up. Through the
    // push the guide stays mostly outward: with the body rolled onto the pulling side, world-up
    // points under the chest, so a large up share would fold the elbow inward. A pull wider than
    // half way reaches out to the side, along that outward guide (under heavy roll exactly along
    // it), so the guide turns back for it: back stays square to an arm reaching out.
    const dropped = lerp(-0.6, 0.35, c) - 0.5 * sag + 0.2 * press, reachOut = smooth(clamp((w - 0.5) / 0.5, 0, 1));
    const elbowDir = [0, 1, 2].map(i => keyed(p, [
      [0, [0.15, 0.75, 0.65][i]], [0.12, [0.15, 0.75, 0.65][i]],
      [0.22, [lerp(-0.1, 0.35, c) - 0.25 * sag, 0.8, dropped][i]],
      [0.36, [lerp(0.15, -0.2, w) - 0.15 * sag - 0.6 * reachOut, 1.0 - 0.3 * reachOut, lerp(0.1, 0.45, w) - 0.4 * sag][i]],
      [push, [-0.6 * reachOut, 0.95 - 0.3 * reachOut, 0.25][i]], [fin, [-0.3, 0.6, 0.7][i]], [1, [0.15, 0.75, 0.65][i]],
    ]));
    // Palm direction for the forearm twist. Down and slightly out at entry, back through the catch
    // and push, pinkie-first and facing the thigh at release, then facing back and out (thumb down)
    // as the elbow lifts, and out to the side as the hand swings forward to the entry. Slip skews the palm inward so it slices rather than holds.
    const SETTLED = 0.14;
    const palm = p >= fin || p < SETTLED ? flowingVector(p < SETTLED ? p + 1 : p, [
      [fin, [-0.2, -0.8, 0.5]], [exit, [-0.2, -0.6, 0.6]],
      [midRec, [-0.6, 0.6, 0.2]], [lateRec, [-0.2, 1, -0.1]],
      [preEntry, [0, 0.45, -1]], [1, [0.1, 0.3, -1]], [1 + SETTLED, [0.1, 0.15, -1]],
    ]) : [0, 1, 2].map(i => keyed(p, [
      [SETTLED, [0.1, 0.15, -1][i]], [0.22, [-0.7, 0, -0.7][i]],
      [0.36, [-1, -0.25 * (1 - w), -0.15][i]], [push, [-1, 0, 0.35][i]], [fin, [-0.2, -0.8, 0.5][i]],
    ]));
    palm[1] -= 0.9 * s * bump(p, 0.14, fin);
    // A dropped elbow leaves the palm facing the floor through the catch: it presses down, not back.
    palm[0] += 0.45 * sag * bump(p, 0.14, 0.42);
    palm[2] -= 0.35 * sag * bump(p, 0.14, 0.42);
    // Wrist press: the palm turns back through the catch instead of down.
    palm[0] -= 0.3 * press * bump(p, 0.14, 0.42);
    palm[2] += 0.2 * press * bump(p, 0.14, 0.42);
    // Over-extension: locked arm, shrugged shoulder, and a "stop sign" wrist that brakes at the front.
    const front = over * keyed(p, [[0, 1], [0.16, 1], [0.30, 0], [0.92, 0], [1, 1]]);
    // Over the water the wrist goes loose: the hand hangs from it, fingers trailing, then firms up
    // for a fingertips-first entry. It starts and ends straight, so the hand never snaps at the exit or entry.
    const relaxed = flowing(p, [[exit, 0], [lift, 22], [midRec, 30], [lateRec, 22], [preEntry, 8], [1, 0]]);
    const wrist = (under ? -48 * s * bump(p, 0.08, exit) + 12 * (1 - s) * bump(p, 0.12, 0.45) - 20 * press * bump(p, 0.14, fin)
      : relaxed) - 32 * front;
    const stage = p < 0.12 ? 0 : p < pull ? 1 : p < push ? 2 : p < fin ? 3 : p < exit ? 4 : 5;
    return {
      x, out, height: height + dy, elbow, recovery, elbowDir, palm, shrug: front,
      reach: rch * keyed(p, [[0, 1], [0.2, 1], [0.36, 0], [preEntry, 0], [1, 1]]),
      wrist: wrist * D, under, stage, load: (P.feel || 0) * loadShare(p, P), pace: loadPace(p, P),
    };
  }

  // Smooth front-end timing adjustment; the pull and recovery keep their original clock phases.
  function strokePhase(p, P) {
    return p < CONFIG.pull ? p - P.frontGlide * Math.sin(Math.PI * p / CONFIG.pull) ** 2 : p;
  }

  // ---- felt load --------------------------------------------------------------
  // The water the hand pushes back pushes back on the palm and forearm, so through the pull the arm
  // feels heavier. Only the sensation grows (buoyancy and the estimates are unchanged), but the arm
  // moves to it: the hand works more slowly through the heaviest water and the weightless recovery
  // makes up the time. P.feel is the peak load (0-1) from Python; a slipping hand feels light.
  // These mirror model.load_profile and model.loaded_time, which place the timeline boundaries.

  // Share of the peak load at arm-path phase p: none in the reach or the air, building through the
  // catch, heaviest as the hand passes under the shoulder, released through the push.
  function loadShare(p, P) {
    const x = (p - CONFIG.catchStart) / (P.exit - CONFIG.catchStart);
    return x > 0 && x < 1 ? Math.sin(Math.PI * x) ** 2 : 0;
  }

  // Clock time per unit of arm path at path phase p: above 1 where the load slows the hand, below 1
  // as it lets go. The water reaction multiplies the measured hand speed by this, because a loaded
  // hand moves slowly by holding the water, not by pushing it less.
  function loadPace(p, P) {
    const x = (p - CONFIG.catchStart) / (P.exit - CONFIG.catchStart);
    if (!(x > 0 && x < 1)) return 1;
    return 1 + CONFIG.loadDwell * clamp(P.feel || 0, 0, 1) * (Math.sin(Math.PI * x) ** 2 - CONFIG.loadRelease * x * x);
  }

  // Clock phase at which the arm reaches path phase s (s <= exit): time at each part of the path
  // grows with the load felt there and shrinks again as the load lets go through the push, so the
  // catch keeps its time. Rush < 1 (spinning arms) squeezes it all.
  function loadedTime(s, P) {
    const span = P.exit - CONFIG.catchStart, x = clamp((s - CONFIG.catchStart) / span, 0, 1);
    const held = span * (x / 2 - Math.sin(2 * Math.PI * x) / (4 * Math.PI) - CONFIG.loadRelease * x ** 3 / 3);
    return P.rush * (s + CONFIG.loadDwell * clamp(P.feel || 0, 0, 1) * held);
  }

  // Clock phase → arm-path phase. Under water this inverts loadedTime (it rises steadily, so halving
  // the interval converges); the recovery fills the rest of the cycle at an even pace.
  function underwater(p, P) {
    if (P.rush === 1 && !P.feel) return p;
    const exit = P.exit, out = loadedTime(exit, P);
    if (p >= out) return exit + (p - out) * (1 - exit) / (1 - out);
    let lo = 0, hi = exit;
    for (let i = 0; i < 32; i++) {
      const mid = (lo + hi) / 2;
      if (loadedTime(mid, P) < p) lo = mid;
      else hi = mid;
    }
    return (lo + hi) / 2;
  }

  // Extra clock time the felt load adds before the hand leaves the water (rush aside).
  const loadDelay = P => CONFIG.loadDwell * clamp(P.feel || 0, 0, 1) * (P.exit - CONFIG.catchStart) * (0.5 - CONFIG.loadRelease / 3);

  // ---- drills -----------------------------------------------------------------
  // Visual only. Each drill remaps the cycle clock onto the two arms; a waiting arm stays long in
  // front at HOLD (just after the entry, arm extended). Returns [right, rightHeld, left, leftHeld].
  // Catch-up gives each arm half of a cycle that Python has made twice as long, so every arm keeps
  // its normal stroke speed and waits in front while the other strokes. Both remaps are continuous:
  // HOLD + 1 wraps back to HOLD.
  const HOLD = 0.10;
  function drillArms(p, P) {
    if (P.drill === 'catchup') {
      const one = q => (q < 0.5 ? [wrap(HOLD + 2 * q), false] : [HOLD, true]);
      return [...one(p), ...one(wrap(p + 0.5))];
    }
    if (P.drill === 'single') return [p, false, HOLD, true];
    return [p, false, wrap(p + 0.5), false];
  }

  // Body timing (roll, kick, snaking) for the clock phase p. In catch-up the body holds on the side of
  // the stroking arm through its catch and pull, then turns over during that arm's push and recovery,
  // so each recovering shoulder is up and the waiting hand catches on its own side. Shifting the
  // two-beat roll by CATCHUP_BODY lands both turns there; the other drills keep the normal timing.
  const CATCHUP_BODY = 0.29;
  const bodyPhase = (p, P) => (P.drill === 'catchup' ? wrap(p + CATCHUP_BODY) : p);

  // Clock phase at which the right arm reaches timeline position f (inverse of drillArms).
  function clockFor(f, P) {
    if (P?.drill !== 'catchup') return f;
    return f >= HOLD ? (f - HOLD) / 2 : (f + 1 - HOLD) / 2;
  }

  // ---- rhythm -----------------------------------------------------------------
  // P.rhythm is the relative time of each stroke in a repeating group (mean 1): [1.45, 0.55] is a gallop
  // (long, short). The waltz keeps even strokes and uses P.rhythmLate instead (see lateWarp). The group is a smooth, monotone
  // warp of the stroke clock, so the arms, roll and kick all speed up and slow down together; the
  // warped clock is what the pose reads (S.rtotal in cycles, S.rphase its fraction). Catch-up and
  // one-arm never get a rhythm (Python sends even strokes there).
  // Each stroke is a cubic ease between its two boundaries. A boundary's speed is the slower of the strokes
  // either side, so a long stroke runs at a steady pace (it never stalls mid-stroke) and a short one speeds
  // up through its middle and eases back at the ends.
  function rhythmWarp(total, d) {
    const n = d.length, sum = d.reduce((a, b) => a + b, 0), key = d.join(',');
    if (S.rkey !== key) {
      const dur = d.map(v => v * n / sum);
      let at = 0;
      S.rcum = dur.map(v => (at += v) - v);
      S.rdur = dur;
      S.rtan = dur.map((v, i) => Math.min(1 / v, 1 / dur[(i + n - 1) % n]));  // speed at each stroke's start
      S.rkey = key;
    }
    const u = 2 * total, g = Math.floor(u / n), x = u - g * n;
    let i = n - 1;
    while (i > 0 && x < S.rcum[i]) i--;
    const dur = S.rdur[i], t = Math.min(1, (x - S.rcum[i]) / dur), t2 = t * t, t3 = t2 * t;
    const m0 = S.rtan[i] * dur, m1 = S.rtan[(i + 1) % n] * dur;
    return (g * n + i + (3 * t2 - 2 * t3) + (t3 - 2 * t2 + t) * m0 + (t3 - t2) * m1) / 2;
  }
  const rhythmOf = P => (P.rhythm && P.rhythm.length > 1 && P.rhythm.some(v => Math.abs(v - 1) > 1e-3) ? P.rhythm : null);
  // Late surge: each stroke (half a cycle) keeps its length but starts slowly and speeds up toward its finish.
  // The speed is 1 + a*sin(2pi(t - 0.55)) over the stroke fraction t, which peaks at 80% and averages 1.
  function lateWarp(total, a) {
    const u = 2 * total, k = Math.floor(u), t = u - k, h = 2 * Math.PI;
    return (k + t + a * (Math.cos(h * 0.55) - Math.cos(h * (t - 0.55))) / h) / 2;
  }
  function warpClock(total, P) {
    const d = rhythmOf(P), a = P.rhythmLate || 0, w = d ? rhythmWarp(total, d) : total;
    return a > 0 ? lateWarp(w, a) : w;
  }
  function applyRhythm(P) {
    S.rtotal = warpClock(S.cycles + S.phase, P);
    S.rphase = wrap(S.rtotal);
  }
  const clockNow = () => S.rphase ?? S.phase;
  // An arm's catch, pull and push all happen in the stroke it enters on, so that stroke's rhythm sets its
  // hold: a short stroke hurries the catch (slips more, shorter path), a long one holds and reaches further.
  // Python sends each stroke's catch, slip, path length, exit and felt load in P.rhythmStrokes (empty when even).
  function strokeParams(P, side) {
    const list = P.rhythmStrokes;
    if (!list || !list.length || S.rtotal === undefined) return P;
    const entry = side === 'R' ? 2 * Math.floor(S.rtotal) : 2 * Math.floor(S.rtotal - 0.5) + 1;
    return {...P, ...list[((entry % list.length) + list.length) % list.length]};
  }
  // Clock phase whose (rhythm-warped) timeline position is f: the timeline marker follows the warped clock.
  function seekPhase(f, P) {
    const base = wrap(clockFor(f, P));
    if (!rhythmOf(P) && !(P.rhythmLate > 0)) return base;
    let best = base, gap = Infinity;
    for (let i = 0; i < 360; i++) {
      const p = i / 360, v = wrap(warpClock(S.cycles + p, P)), e = Math.abs(v - f);
      if (Math.min(e, 1 - e) < gap) { gap = Math.min(e, 1 - e); best = p; }
    }
    return best;
  }

  // Fist drill: the hands close (thumbs tucked), so the palm loads little and the forearm does the catching.
  const FIST_GAIN = { wr: 0.25, el: 1.5 };
  // Hand paddles enlarge the palm, so the hand probe loads more water (not with the fist drill).
  const paddled = P => !!S.faults.paddles && P.drill !== 'fist';
  const probeGain = (p, P) => p.gain * (P.drill === 'fist' && p.hand ? FIST_GAIN[p.joint.slice(0, 2)] : 1)
    * (paddled(P) && p.joint.startsWith('wr') ? CONFIG.paddleArea : 1);
  function shapeHands(m, P) {
    const fist = P.drill === 'fist';
    if (m.fist === fist) return;
    m.fist = fist;
    for (const side of ['R', 'L']) {
      const hand = m['ha' + side], base = m.handBase[side];
      if (fist) {
        hand.scale.set(0.05, 0.045, 0.036);
        hand.position.x = 0.04;
      } else {
        hand.scale.copy(base.scale);
        hand.position.copy(base.position);
      }
      m['thumb' + side].visible = !fist;
    }
  }

  // Show the hand paddles while they are switched on; a closed fist drill takes them off.
  function showPaddles(m, P) {
    const on = paddled(P);
    m.padR.visible = m.padL.visible = on;
  }

  // ---- natural motion ---------------------------------------------------------
  // Visual only: these never touch the phase, the timeline, or the Python metrics.
  // Variation is keyed to stroke time (cycles + phase), so it holds still while paused.

  // One breath every P.breath strokes (default three: bilateral, alternating sides). The head turns
  // toward the arm as it finishes and starts its recovery, then rotates back down by the end of the
  // recovery, before that hand enters again. Odd counts alternate sides; even counts always breathe
  // right. rightArm and leftArm are each arm's clock phase after any drill remap.
  // Returns -1..1: negative turns the face to the right (-y), positive to the left.
  function breathing(P, rightArm, leftArm) {
    // A loaded hand leaves the water a little later (see loadedTime); the breath waits for it.
    const t = S.rtotal ?? S.cycles + S.phase, exit = P.exit + loadDelay(P), every = P.breath || 3;
    const turnWindow = p => keyed(p, [[exit - 0.22, 0], [exit - 0.04, 1], [exit + 0.08, 1], [exit + 0.2, 0]]);
    const breathes = n => ((n % every) + every) % every === 0;  // n counts hand entries: right even, left odd
    const right = breathes(2 * Math.floor(t)) ? turnWindow(rightArm) : 0;
    const left = breathes(2 * Math.floor(t - 0.5) + 1) ? turnWindow(leftArm) : 0;
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
    for (const k of ['chainR', 'chainL', 'chainPulseR', 'chainPulseL']) {
      Object.assign(m[k].material, { depthWrite: false, depthTest: false, transparent: true });
      m[k].renderOrder = 11;
    }
    m.basePos = m.buoys.map(b => b.position.x);
    // Roll about the body axis first, then yaw it (snaking) in the water plane.
    m.chest.rotation.order = 'ZYX';
    m.pelvis.rotation.order = 'ZYX';
    // The head pivots at the base of the neck: turn about the spine to breathe, then lift (head-lift fault).
    m.head.rotation.order = 'YXZ';
    m.handBase = Object.fromEntries(['R', 'L'].map(s => [s, {
      scale: m['ha' + s].scale.clone(), position: m['ha' + s].position.clone(),
    }]));
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
        outgoingLight = mix( outgoingLight, vec3( 0.44, 0.70, 0.78 ), lcFresnel * 0.45 );
        diffuseColor.a = min( diffuseColor.a * ( 1.0 + lcFresnel * 1.5 ), 0.45 );
        ${out}`);
    };
  }

  // Replace NiceGUI's flat default lights (strong ambient + one overhead light) with a higher-contrast rig.
  // White light keeps the palette colours strong. A sky/pool hemisphere light replaces most of the flat
  // ambient, so upper surfaces read pale and undersides take a cool teal tint; a key light from above-front
  // adds shading, and a cool rim light from behind separates the swimmer from the dark water.
  // No shadows, so rendering cost is unchanged.
  function setupLighting(group) {
    for (const light of S.el.scene.children.filter(o => o.isAmbientLight || o.isDirectionalLight)) {
      S.el.scene.remove(light);
    }
    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(3, -2.5, 6);
    const rim = new THREE.DirectionalLight(0x9fe4ff, 0.9);
    rim.position.set(-4, 3, -1.5);
    const sky = new THREE.HemisphereLight(0xe4f6ff, 0x1d5562, 1.2);
    sky.position.set(0, 0, 1);
    group.add(new THREE.AmbientLight(0xffffff, 0.6), sky, key, rim);
    // A faint haze in the background colour: the far lane rope and the end of the pool fade into the dark.
    S.el.scene.fog = new THREE.FogExp2(CONFIG.background, 0.06);
  }

  // Render at the screen's pixel density (capped at 2x), so edges stay crisp on high-DPI displays.
  function sharpen(renderer) {
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    if (renderer.getPixelRatio() === ratio) return;
    const size = renderer.getSize(new THREE.Vector2());
    renderer.setPixelRatio(ratio);
    renderer.setSize(size.x, size.y, false);
  }

  // A soft sheen: skin and suit catch a little light; the silicone cap and the plastic paddles get a
  // brighter, tighter highlight.
  function setupSheen(m) {
    const cap = new THREE.Color(CONFIG.colors.cap), paddle = new THREE.Color(CONFIG.colors.paddle);
    for (const part of [m.chest, m.pelvis]) {
      part.traverse(o => {
        const mat = o.material;
        if (!o.isMesh || !mat || !mat.isMeshPhongMaterial || mat.opacity === 0) return;
        const shiny = mat.color.equals(cap) || mat.color.equals(paddle);
        mat.specular.setScalar(shiny ? 0.18 : 0.1);
        mat.shininess = shiny ? 40 : 16;
      });
    }
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
    // A soft contact shadow on the floor, well below: the swimmer blocks the light from above.
    const shade = canvasTexture(128, (g, n) => {
      const grad = g.createRadialGradient(n / 2, n / 2, 0, n / 2, n / 2, n / 2);
      grad.addColorStop(0, 'rgba(0,15,25,0.9)');
      grad.addColorStop(1, 'rgba(0,15,25,0)');
      g.fillStyle = grad;
      g.fillRect(0, 0, n, n);
    });
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.1), new THREE.MeshBasicMaterial({
      map: shade, transparent: true, depthWrite: false, opacity: 0.45,
    }));
    shadow.position.z = FLOOR_Z + 0.012;
    shadow.renderOrder = 0;
    pool.add(shadow);
    scene.add(pool);
    setupLighting(pool);
    sharpen(S.el.renderer);
    setupSheen(m);
    const pos = m.water.geometry.attributes.position, a = pos.array;
    const fixed = new Float64Array(pos.count), bow = new Float64Array(pos.count), heights = new Float64Array(pos.count);
    for (let i = 0; i < pos.count; i++) {
      const x = a[3 * i] + SURFACE.x, y = a[3 * i + 1], d = 0.55 - x;
      // Bow wave: a hump pushed up ahead of the head and a trough beside the shoulders.
      bow[i] = 0.034 * Math.exp(-((x - 0.62) ** 2) / 0.025 - y * y / 0.04)
        - 0.022 * Math.exp(-((x - 0.3) ** 2) / 0.04 - y * y / 0.1);
      fixed[i] = 0;
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
    m.pool = { tiles, caustics, shadow, flow, ripple, rippleB, fixed, bow, heights, waves, time: 0, dirty: true };
    return true;
  }

  // Move the swell, bow wave, wake, kick wash, and splash ripples, and scroll the floor back at
  // swim speed (so the pool slides past).
  function updateWater(m, P, dt) {
    if (!setupWater(m)) return;
    const pool = m.pool, t = (pool.time += dt), off = S.offset, fx = m.fx;
    const at = m.chest.getWorldPosition(pool.at ||= S.el.scene.position.clone());
    pool.shadow.position.set(at.x - 0.35, at.y, pool.shadow.position.z);
    const pos = m.water.geometry.attributes.position, a = pos.array;
    const pace = Math.min(1, P.speed), ripples = fx ? fx.ripples : [], wash = fx ? fx.wash : 0, footX = fx ? fx.footX : -1.6;
    // A lifted head ploughs a bigger bow wave; a buried one rides under it.
    const {hi, lo} = headOff(P), bowGain = pace * (1 + 1.6 * hi - 0.5 * lo);
    if (dt === 0 && !pool.dirty && pool.pace === pace && pool.bowGain === bowGain) return;
    const heights = pool.heights, [wave0, wave1, wave2] = pool.waves;
    const [c0, s0, c1, s1, c2, s2] = SWELL.flatMap(([kx, , kt]) => {
      const phase = kx * off + kt * t;
      return [Math.cos(phase), Math.sin(phase)];
    });
    for (let i = 0; i < pos.count; i++) {
      const x = a[3 * i] + SURFACE.x + off, y = a[3 * i + 1], lx = a[3 * i] + SURFACE.x;
      const j = 2 * i;
      let h = wave0[j] * c0 + wave0[j + 1] * s0 + wave1[j] * c1 + wave1[j + 1] * s1
        + wave2[j] * c2 + wave2[j + 1] * s2 + pool.fixed[i] * pace + pool.bow[i] * bowGain;
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
    pool.bowGain = bowGain;
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
    maxRipples: 24, maxBubbles: 420, maxSpray: 160, maxPressure: 700, maxFlow: 700, rippleSpeed: 0.55, gravity: 9.81, rise: 0.28,
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

  function updatePressure(fx, m, P, dt, slipness, flow, emitting = true) {
    const sys = fx.pressure;
    for (const pr of fx.probes) {
      const joint = m[pr.joint];
      joint.localToWorld(pr.pos.set(...pr.at));
      if (pr.known) pr.vel.subVectors(pr.pos, pr.prev).divideScalar(dt);
      if (pr.hand && m.pace) pr.vel.multiplyScalar(m.pace[pr.joint.slice(-1)]);
      pr.prev.copy(pr.pos);
      const wasKnown = pr.known;
      pr.known = true;
      if (!emitting || !wasKnown || pr.pos.z > -0.03) continue;
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
      const hold = pr.hand ? 1 - 0.9 * (m.slip ? m.slip[pr.joint.slice(-1)] : slipness) : 1;
      const rate = Math.min(320, 90 * probeGain(pr, P) * hold * q * q);
      for (let i = spawnCount(rate * dt); i > 0; i--) {
        const push = 0.55 * q * rand(0.6, 1.1);
        emit(sys, pr.pos.x + 0.03 * pr.n.x + rand(-0.03, 0.03), pr.pos.y + 0.03 * pr.n.y + rand(-0.03, 0.03),
          pr.pos.z + 0.03 * pr.n.z + rand(-0.02, 0.02),
          -flow + push * pr.n.x + rand(-0.15, 0.15), push * pr.n.y + rand(-0.15, 0.15), push * pr.n.z + rand(-0.1, 0.1),
          rand(0.8, 1.4), clamp(0.35 + 0.35 * q, 0.35, 1));
      }
    }
  }

  // Water flow view (visual only): tracers released at each pulling palm. The share that holds is
  // carried back with the hand (teal); the share that slips escapes sideways around the palm's edge
  // while the hand slides on (red), and any sideways sweep of the palm (a wide pull, a snaking body)
  // adds to the spill. Slipping is read from the same per-arm value that colours the hand.
  function updateFlow(fx, m, P, dt, flow) {
    const sys = fx.flowSys;
    for (const pr of fx.probes) {
      if (!pr.hand || !pr.joint.startsWith('wr') || !pr.known || pr.pos.z > -0.03) continue;
      const arm = pr.joint.slice(-1), slip = clamp(m.slip ? m.slip[arm] : 0, 0, 1);
      const joint = m[pr.joint], n = pr.n.set(0, 0, -1).transformDirection(joint.matrixWorld);
      const v = pr.vel, push = Math.max(0, v.dot(n));
      const side = Math.abs(v.y) + 0.5 * Math.hypot(v.x + flow, v.y) * slip;  // sideways slide of the palm
      const rate = Math.min(600, 120 + 300 * (push + 0.6 * side));
      for (let i = spawnCount(rate * dt); i > 0; i--) {
        const spill = Math.random() < clamp(slip + 0.5 * clamp(side, 0, 1), 0, 1);
        const sign = (v.y !== 0 ? Math.sign(v.y) : (arm === 'R' ? -1 : 1)) * (spill ? 1 : 0);
        const hold = spill ? 0.15 : 0.55;
        emit(sys, pr.pos.x + rand(-0.04, 0.04), pr.pos.y + rand(-0.05, 0.05), pr.pos.z + rand(-0.03, 0.03),
          -flow + v.x * hold + (spill ? rand(-0.1, 0.1) : 0), v.y * hold + sign * rand(0.5, 1.3) * (0.4 + slip),
          v.z * hold + (spill ? rand(-0.05, 0.12) : 0), rand(1.2, 2.0), spill ? 1 : 0);
      }
    }
  }

  function drawTracers(sys) {
    const [hr, hg, hb] = C.hold, [sr, sg, sb] = C.slip, list = sys.list;
    for (let i = 0; i < list.length; i++) {
      const q = list[i], age = q[6] / q[7], spill = q[8];
      sys.pos[3 * i] = q[0]; sys.pos[3 * i + 1] = q[1]; sys.pos[3 * i + 2] = q[2];
      sys.col[4 * i] = spill ? sr : hr; sys.col[4 * i + 1] = spill ? sg : hg; sys.col[4 * i + 2] = spill ? sb : hb;
      sys.col[4 * i + 3] = 0.75 * Math.min(1, q[6] / 0.05) * (1 - age) ** 0.8;
    }
    sys.geo.attributes.position.needsUpdate = true;
    sys.geo.attributes.color.needsUpdate = true;
    sys.geo.setDrawRange(0, list.length);
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
      flowSys: makeParticles(group, FX.maxFlow, 0.14, [1, 1, 1]),
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
    // Flow tracers: held water settles into the stream with the body; spilled water keeps sliding sideways.
    compact(fx.flowSys.list, q => {
      const k = q[8] ? 0.9 : 2.0;
      q[3] += (-flow - q[3]) * Math.min(1, k * dt); q[4] -= q[4] * Math.min(1, (q[8] ? 0.5 : 2.0) * dt);
      q[5] -= q[5] * Math.min(1, 2 * dt);
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
      fx.ripples.length = fx.bubbles.list.length = fx.spray.list.length = fx.pressure.list.length = fx.flowSys.list.length = 0;
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
      if (P.pressure || P.flow) updatePressure(fx, m, P, dt, slipness, flow, !!P.pressure);
      if (P.flow) updateFlow(fx, m, P, dt, flow);
      stepFx(fx, flow, dt);
    }
    if (!P.pressure) fx.pressure.list.length = 0;
    if (!P.flow) fx.flowSys.list.length = 0;
    drawTracers(fx.flowSys);
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
    // Close-up that follows whichever hand is deeper (the one pulling), seen from the side.
    hand: { dir: [0.25, -1, 0.12], up: [0, 0, 1], half: [0.55, 0.38], follow: true },
  };
  const handScratch = [];
  // Adopt a scene_view as the second camera; retries until NiceGUI has mounted it.
  function setView(viewId, angle) {
    const el = typeof getElement === 'function' ? getElement(viewId) : null;
    if (!el || !el.renderer || !el.camera) { setTimeout(() => setView(viewId, angle), 100); return; }
    if (!S.view || S.view.el !== el) {
      el.renderer.setClearColor(CONFIG.background);
      sharpen(el.renderer);
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
    const zoom = 1 - CATCH_ZOOM * (S.params && S.params.catchFocus ? S.catchEnv || 0 : 0);
    const half0 = spec.follow && S.params && S.params.flow ? [0.6, 0.4] : spec.half;  // flow: the whole stroke in frame
    const half = [half0[0] * zoom, half0[1] * zoom];
    const dist = Math.max(spec.min || 0, 1.15 * half[1] / t, 1.15 * half[0] / (t * w / h));
    v.dir.set(...spec.dir).normalize();
    cam.up.set(...spec.up);
    if (spec.follow && S.m && S.m.wrR) {
      // Follow the deeper wrist; switch hands only when the other is clearly deeper, and ease the target.
      const [r, l] = handScratch.length ? handScratch : (handScratch.push(new THREE.Vector3(), new THREE.Vector3()), handScratch);
      S.m.wrR.getWorldPosition(r);
      S.m.wrL.getWorldPosition(l);
      const deeper = r.z < l.z ? 'R' : 'L';
      if (!v.hand || (deeper !== v.hand && Math.abs(r.z - l.z) > 0.04)) v.hand = deeper;
      let goal = v.hand === 'R' ? r : l, ease = 0.2;
      if (S.params && S.params.flow) {
        // Water flow: hold still on the pulling side's whole stroke (shoulder to hip, a little ahead of
        // the shoulder), so the tracers read against a steady frame instead of a camera chasing the hand.
        const sh = v.hand === 'R' ? S.m.shR : S.m.shL;
        sh.getWorldPosition(r);
        goal = r.set(r.x + 0.1, r.y, -0.3);
        ease = 0.03;
      }
      if (v.followed) v.target.lerp(goal, ease); else { v.target.copy(goal); v.followed = true; }
    } else if (!spec.follow) {
      v.followed = false;
      v.target.set(-0.25, 0, -0.12);
    }
    cam.position.copy(v.target).addScaledVector(v.dir, dist);
    cam.lookAt(v.target);
  }

  // ---- posing -----------------------------------------------------------------

  // Underwater forearm and hand fade from teal (holding) to red (slipping); skin colour in the air.
  function paint(mesh, under, slipness) {
    const col = under ? C.hold.map((v, i) => lerp(v, C.slip[i], slipness)) : C.skin;
    mesh.material.color.setRGB(col[0], col[1], col[2]);
  }

  // Fixed-length two-bone inverse kinematics for one arm in the rolled chest frame.
  function poseArm(m, side, a, P, slipness, bodyRoll, pitch = 0) {
    const sgn = side === 'R' ? -1 : 1, sh = m['sh' + side], r = m.rigs[side];
    const cos = Math.cos(bodyRoll), sin = Math.sin(bodyRoll);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    sh.position.x = r.baseX + 0.04 * a.shrug + 0.05 * a.reach;
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
    // Only a short guide needs it: a clear one (a quarter or more of its length left off the arm)
    // keeps its own direction. Enforced on a clear guide that points away from the hint, the minimum
    // swung the elbow half a turn whenever either one turned past the other, and under heavy roll
    // with a wide pull the hint itself turns fast (see below).
    const guide = r.pole.length();
    r.hint.set(0.5, sgn, 0);
    r.hint.addScaledVector(r.axis, -r.hint.dot(r.axis));
    // A wide pull points the arm itself out and forward, along that guide; its remainder then shrinks
    // and flips side. Blend in "up" (toward the back) as it shrinks, so the hint never vanishes.
    const spread = r.hint.length(), up = smooth(clamp((0.42 - spread) / 0.42, 0, 1));
    r.normal.set(0, 0, 1).addScaledVector(r.axis, -r.axis.z);
    r.hint.addScaledVector(r.normal, up).normalize();
    const share = r.pole.dot(r.hint), floor = lerp(0.25, -2, smooth(clamp(guide / 0.25, 0, 1)));
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
    // A positive bound saturates smoothly (tanh, not a clamp): under heavy roll the catch starts with
    // the elbow pinned fully outward, and a clamped bound then released it so fast as the elbow bent
    // that the bend plane, and with it the hand, swung tens of degrees in a single frame. A negative
    // bound stays linear down to -1, where it never applies.
    r.z.set(0, sgn, 0).addScaledVector(r.axis, -sgn * r.axis.y).normalize();
    const bound = (0.015 - along * sgn * r.axis.y) / (lift * Math.sqrt(1 - r.axis.y ** 2));
    const minOut = bound > 0 ? Math.tanh(bound) : Math.max(bound, -1);
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
  const kickTiming = (P, F) => (F.kneekick || F.samesidekick ? 0 : clamp((6 - (P.beats ?? 6)) / 4, 0, 1));

  // Healthy kicks drive from the hips; a knee kick drops the thighs and bends the knees hard.
  // Each beat varies a little in size and timing (t is stroke time; zero kick stays still).
  // `body` is the body-timing phase: the clock phase, shifted in a catch-up drill (see bodyPhase).
  function poseLegs(m, P, F, t, body) {
    const knees = F.kneekick ? 1 : 0, base = knees ? Math.max(P.kick, 0.6) : P.kick;
    const beats = knees ? 6 : P.beats ?? 6;
    // The flutter shares the two-beat timing: each leg's downbeat lands with the opposite catch.
    const kick = 2 * Math.PI * (beats / 2) * (body - P.catchDelay - KICK_START);
    m.kickPulse = m.kickPulse || {};
    for (const [side, offset] of [['R', 0], ['L', Math.PI]]) {
      const k = base * (1 + 0.12 * noise(3 * t, offset ? 52 : 51));
      if (beats === 2 && !knees) {
        // Bigger single beats: the downbeat has to turn the hips as well as balance the legs.
        const q = wrap(body - P.catchDelay - KICK_START - (offset ? 0 : 0.5) - (F.samesidekick ? 0.5 : 0)
          + 0.01 * noise(2 * t, offset ? 62 : 61));
        const big = 1.25 * k;
        m['leg' + side].rotation.set(0, big * keyed(q, TWO_BEAT.hip), 0);
        m['knee' + side].rotation.set(0, big * keyed(q, TWO_BEAT.knee), 0);
        m['ankle' + side].rotation.set(0, -0.12 - 0.35 * big * keyed(q, TWO_BEAT.ankle), 0);
        // Pulse progress up the cross-body link: starts with the downbeat's snap, about a third of a cycle.
        m.kickPulse[side] = base > 0.05 && q > 0.03 && q < 0.33 ? (q - 0.03) / 0.3 : -1;
        continue;
      }
      const angle = kick + offset + (F.samesidekick ? Math.PI : 0) + 0.15 * noise(2 * t, offset ? 62 : 61);
      const hip = knees ? -0.12 * k + 0.06 * k * Math.sin(angle) : 0.26 * k * Math.sin(angle);
      const knee = knees ? 0.2 + 1.3 * k * Math.max(0, Math.sin(angle - 0.3)) : 0.45 * k * Math.max(0, Math.sin(angle - 0.7));
      m['leg' + side].rotation.set(0, hip, 0);
      m['knee' + side].rotation.set(0, knee, 0);
      m['ankle' + side].rotation.set(0, -0.12 + k * (knees ? 0.25 : 0.10) * Math.sin(angle - 0.5), 0);
      // Each flutter downbeat sends a shorter pulse (0.15 of a cycle) from just before its snap.
      const u = wrap((angle - 0.5 - Math.PI / 2) / (2 * Math.PI) + 0.04), span = 0.075 * beats;
      m.kickPulse[side] = base > 0.05 && u < span ? u / span : -1;
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

  // Arm-phase labels, cycle percentage, and timeline marker. The timeline follows the right arm, so
  // in a catch-up drill the marker parks in the entry while that arm waits in front.
  // Felt-load bar under an arm's phase, in that arm's hand colour (teal holding, coral slipping).
  function setLoad(key, selector, load, colour) {
    const node = find(key, selector);
    if (!node) return;
    const scale = clamp(load, 0, 1).toFixed(2);
    if (S.ui[key + 'At'] !== scale) { node.style.transform = `scaleX(${scale})`; S.ui[key + 'At'] = scale; }
    if (S.ui[key + 'Colour'] !== colour) { node.style.background = colour; S.ui[key + 'Colour'] = colour; }
  }

  function updateHud(right, left, slipness) {
    const tag = s => {
      const angle = S.params.catchFocus && S.focus?.[s]?.fore.visible ? ` ${Math.round(S.focus[s].angle)}°` : '';
      const slide = S.params.anchor && S.anchors?.[s]?.slideCm >= 0 ? ` · slid ${Math.round(S.anchors[s].slideCm)} cm` : '';
      return angle + slide;
    };
    setText('right', '.lc-arm-right', right.held ? 'Holding' : PHASES[right.stage] + tag('R'));
    setText('left', '.lc-arm-left', left.held ? 'Holding' : PHASES[left.stage] + tag('L'));
    const colour = `rgb(${C.hold.map((v, i) => Math.round(255 * lerp(v, C.slip[i], slipness))).join(', ')})`;
    setLoad('rightLoad', '.lc-load-right .lc-load-fill', right.load, colour);
    setLoad('leftLoad', '.lc-load-left .lc-load-fill', left.load, colour);
    const shown = drillArms(clockNow(), S.params)[0];
    setText('cycle', '.lc-cycle', Math.floor(shown * 100 + 1e-8) % 100 + '%');
    const marker = find('marker', '.lc-timeline-marker');
    const position = (shown * 100).toFixed(1) + '%';
    if (marker && S.ui.markerAt !== position) { marker.style.left = position; S.ui.markerAt = position; }
    const timeline = find('timeline', '.lc-timeline');
    if (timeline && timeline.dataset.stage !== String(right.stage)) timeline.dataset.stage = right.stage;
    const percent = String(Math.floor(shown * 100));
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
    // Catch focus eases the clock down to a fifth of its speed through each catch; the ease keeps the
    // slow-down and the zoom from snapping at the window's edges.
    const target = catchFocusEnv(P);
    S.catchEnv = lerp(S.catchEnv ?? 0, target, 1 - Math.exp(-12 * dt));
    const scaled = P.playing && !S.seekPausePending ? dt * (P.playback || 1) * (1 - CATCH_SLOW * S.catchEnv) : 0;
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
    // A loose core: part of each pull twists the trunk toward the pulling arm instead of moving the body.
    const leak = 1 - coreLink(P, S.faults);
    body.updateMatrixWorld(true);
    for (const p of m.probes) {
      const joint = m[p.joint];
      joint.localToWorld(p.pos.set(...p.at));
      if (dt > 0 && p.known) {
        p.velocity.subVectors(p.pos, p.prev).divideScalar(dt).clampLength(0, 3);
        if (p.hand) p.velocity.multiplyScalar(m.pace[p.joint.slice(-1)]);
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
        const grip = p.hand ? m.grip[p.joint.slice(-1)] : 0.2 * P.kick;
        const load = -probeGain(p, P) * wet * grip * q * Math.abs(q);
        const fx = load * p.normal.x, fy = load * p.normal.y, fz = load * p.normal.z;
        if (p.hand) {
          forward += fx * (1 - 0.35 * leak);
          torque -= 0.35 * leak * Math.abs(fx) * Math.sign(p.pos.y);
        }
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
    // A lifted head drops the hips for the length of each breath; a kick holds sinking legs up a little.
    // A head held high or buried drags all the time.
    const head = headOff(P);
    const dragShape = 1 + 2 * P.hipDrop + 0.35 * legSink(P, S.faults) + 0.6 * head.hi + 0.25 * head.lo + 0.4 * Math.max(0, (P.arch ?? 0) - 8) / 22
      + (S.faults.headlift ? 0.5 * Math.abs(breath) : 0) + 2 * Math.abs(s.pitch) + 0.12 * legDrag;
    // Imbalance (a head held high, a hollow back, sinking legs) makes the body rock: the front lifts and
    // the hips drop with each pull, bobbing, and the tail fishtails a little. Zero when balanced.
    const imb = Math.max(head.hi, 0.6 * head.lo, Math.max(0, (P.arch ?? 0) - 8) / 22, legSink(P, S.faults) * 0.7);
    const rock = imb * Math.sin(4 * Math.PI * clockNow()), fishtail = imb * Math.sin(2 * Math.PI * clockNow());
    const steps = Math.ceil(dt * 120), h = steps ? dt / steps : 0;
    for (let i = 0; i < steps; i++) {
      s.load += (Math.max(0, forward) - s.load) * (1 - Math.exp(-h * P.rate / 240));
      const drag = 0.6 * Math.max(0.015, s.load) * dragShape / Math.max(0.04, P.speed ** 2);
      const kickThrust = 0.16 * Math.max(0.015, s.load) * Math.tanh(kickDrive / 0.12);
      s.speed = clamp(s.speed + (0.6 * (forward + kickThrust) - drag * s.speed ** 2) * h,
        0.15 * P.speed, 1.7 * P.speed);
      s.surge += (s.speed - P.speed - 1.3 * s.surge) * h;
      s.turn += (2.4 * (torque + 0.12 * fishtail) - 5 * s.turn) * h;
      s.yaw += s.turn * h;
      s.drift += (0.8 * sideways + s.speed * Math.sin(4 * D * Math.tanh(s.yaw / (4 * D)))
        - 4 * s.drift) * h;
      s.sway += s.drift * h;
      s.rise += (0.12 * vertical + 22 * (0.006 * Math.abs(breath) + 0.009 * rock - s.height) - 7 * s.rise) * h;
      s.height += s.rise * h;
      s.pitchRate += (0.14 * tipping - 18 * (s.pitch + 0.7 * D * Math.abs(breath) + 4 * D * rock) - 6 * s.pitchRate) * h;
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

  // Head position (P.head, degrees from the spine line, + looks forward): how far (0-1) it sits past the
  // neutral band toward the lifted (hi) or buried (lo) end of its slider, as in model.head_drag.
  function headOff(P) {
    const [lo, hi] = CONFIG.headBand, [min, max] = CONFIG.headRange, h = P.head ?? 5;
    return {hi: clamp((h - hi) / (max - hi), 0, 1), lo: clamp((lo - h) / (lo - min), 0, 1)};
  }
  // Sinking legs, less the share a kick holds up (model.KICK_LIFT): 0 without the fault.
  const legSink = (P, F) => (F.sinking ? 1 - CONFIG.kickLift * P.kick : 0);
  // The legs also sink deeper the faster the swimmer goes (model.sink_scale: drag grows with speed squared).
  const sinkAtPace = (P, F) => legSink(P, F)
    * clamp((P.speed / CONFIG.sinkRefSpeed) ** 2, CONFIG.sinkSpeedRange[0], CONFIG.sinkSpeedRange[1]);
  // Lopsided pull: the right arm catches late and weak and slips, while the left holds.
  const lopsided = P => ({...P, catch: P.catch * CONFIG.lopsidedCatch, slip: clamp(P.slip + 0.2, 0, 1)});
  const slipShare = P => smooth(clamp((0.75 * P.slip + 0.5 * (1 - P.catch) - 0.25) / 0.3, 0, 1));
  // A loose core also gives the hand less to push against, so it holds the water less firmly.
  const gripOf = (P, slipness) => (1 - 0.9 * slipness) * (0.35 + 0.65 * P.catch) * (0.55 + 0.45 * coreLink(P, S.faults));

  // Gaze line (visual only): with the head outside its neutral band a coral line runs from the goggles
  // along the line of sight, forward toward the wall when lifted, back toward the hips when tucked.
  // It is a child of the head, so it turns with the breath and the head angle.
  function showGaze(m, head) {
    const off = Math.max(head.hi, head.lo);
    if (!m.gaze) {
      if (!off) return;
      const geometry = new THREE.CylinderGeometry(0.006, 0.006, 1, 8).translate(0, -0.5, 0).rotateX(Math.PI / 2);
      m.gaze = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
        color: new THREE.Color(...C.slip), transparent: true, depthWrite: false,
      }));
      m.gaze.position.set(0.25, 0, -0.09);  // between the goggles, in the head's frame (swimmer.py)
      m.head.add(m.gaze);
    }
    m.gaze.visible = off > 0;
    m.gaze.material.opacity = 0.4 + 0.5 * Math.min(1, 3 * off);
  }

  function poseSwimmer(P, m, scaled, resetMotion) {
    // Measure the prescribed stroke in a neutral frame, never the previous steering response.
    const previousX = m.chest.parent.position.x;
    m.chest.parent.rotation.set(0, 0, 0);
    m.chest.parent.position.copy(m.bodyOrigin);
    // The swimmer's height scales the whole body about its centre (1 = the 180 cm model).
    m.chest.parent.scale.setScalar(P.scale || 1);
    if (scaled > 0) {
      // A catch-up drill stretches the cycle (cycleScale) so each arm keeps its normal speed.
      const next = S.phase + scaled / ((120 / P.rate) * (P.cycleScale || 1));
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
    applyRhythm(P);
    const [rightArm, rightHeld, leftArm, leftHeld] = drillArms(S.rphase, P);
    const F = S.faults, w = 2 * Math.PI, st = S.cycles + S.phase, breath = breathing(P, rightArm, leftArm);
    const chestGain = F.overrotation ? 1.65 : F.flathips ? 1.25 : 1;
    const roll = Math.min(80, P.roll * chestGain * (1 + 0.04 * noise(2 * st, 11))) * D;
    const lead = 0.07 * P.drive - 0.05 * (1 - P.drive);
    // Hip finish & roll: the hips turn with the shoulders, one unit about a still head (a corkscrew).
    const hipShare = F.flathips ? 0.06 : F.overrotation ? 0.85 : F.hipfinish ? 0.85 : 0.3 + 0.6 * P.drive;
    // Two-beat timing: the kick turns the hips first and the chest follows a moment later, then both
    // hold on the side. A six-beat kick leaves the steady, even rotation. Catch-up always holds on the
    // side, on its own timing (see bodyPhase).
    const body = bodyPhase(S.rphase, P), sharp = P.drill === 'catchup' ? 1 : kickTiming(P, F);
    const rollAt = p => lerp(Math.cos(w * (p - ROLL_PEAK)), kickRoll(p - P.catchDelay), sharp);
    // Early rotation: while an arm is still pushing, the body is already rolling to the next side, the
    // shoulders well ahead of the hips (twice the turn), so the torso twists. `early` is non-zero only
    // in the push (positive for the right arm), so the recovery and entry keep their normal roll.
    const early = F.earlyroll ? bump(rightArm, 0.45, 0.8) - bump(leftArm, 0.45, 0.8) : 0;
    const turnEarly = (v, share) => lerp(v, -Math.sign(early), share * Math.abs(early));
    const bodyRoll = roll * turnEarly(rollAt(body - 0.04 * sharp), 0.7) + 6 * D * breath;
    // Head lift: each breath lifts the head forward, tips the chest up and lets the hips sink.
    // Head position: a lifted head tips the chest up and lets the hips and legs sink; a buried head
    // (chin tucked) drives the chest down and the hips up.
    const lift = F.headlift ? Math.abs(breath) : 0, sink = sinkAtPace(P, F), head = headOff(P);
    // The chest leans up and out from the hips: the pelvis and legs stay low as the pivot while the back
    // arches and the chest rises forward, instead of the whole body tilting as one.
    const arch = Math.min(1, 0.5 * sink + 0.6 * lift + 0.9 * head.hi);
    // The Back arch slider adds to that. The arch swells as the hips turn through the middle of each roll
    // (twice a stroke) and eases to a new setting instead of snapping; paused, it jumps to the setting.
    const set = P.arch ?? 0, archWant = 10 * D * arch + 0.5 * set * D * (1 + 0.18 * Math.cos(2 * w * (body - ROLL_PEAK)));
    S.arch = S.arch === undefined ? archWant : lerp(S.arch, archWant, scaled > 0 ? settle : 1);
    const pitchBase = -14 * D * sink - 8 * D * lift - 7 * D * head.hi + 6 * D * head.lo;
    const pitch = pitchBase - S.arch;
    const legPitch = -24 * D * sink - 10 * D * lift - 16 * D * head.hi + 5 * D * head.lo - 0.3 * Math.max(0, set - 8) * D;
    // Snaking: the chest yaws with each sweep and the hips swing the other way behind it.
    // A loose core lets each pull bend the trunk: the chest turns toward the pulling arm, the hips the other way.
    const leak = 1 - coreLink(P, F);
    const yaw = ((F.snaking ? 7 : F.samesidekick ? 3 : 0) + 4 * leak) * D * Math.sin(w * (body - ROLL_PEAK))
      + 0.8 * D * noise(st, 31);
    m.chest.rotation.set(bodyRoll, pitch, yaw);
    // Hip turn: extra degrees on the pelvis alone, so the hips lead a relaxed chest (flat hips lose it).
    const hipPeak = Math.min(90 * D, roll * hipShare + (P.hips ?? 0) * D * (F.flathips ? 0.1 : 1));
    m.pelvis.rotation.set(hipPeak * turnEarly(rollAt(body + lead * (1 - sharp)), 0.35), legPitch, -1.8 * yaw);
    m.pelvis.position.y = -0.36 * Math.sin(yaw);
    // Keep the waist joined to the pitched chest, then let the hips drop a little further.
    m.pelvis.position.x = -0.36 * Math.cos(pitch);
    // Keep only small pose variation here; the common body parent carries buoyancy and pull lift.
    const heave = 0.003 * noise(1.5 * st, 21);
    // The hips hold their place, so the chest lifts by what the arch adds.
    m.chest.position.z = heave + S.ride.height - 0.025 * head.lo + 0.36 * (Math.sin(pitchBase) - Math.sin(pitch));
    m.pelvis.position.z = 0.36 * Math.sin(pitchBase) - 0.05 * sink - 0.05 * head.hi + 0.015 * head.lo
      + 0.6 * heave + S.ride.height - S.ride.hips;
    // The head stays steady while the body rolls beneath it (the neck takes up half the roll),
    // then turns with the roll to breathe, one goggle staying in the water. A head lifter turns
    // less and lifts the face forward out of the water instead.
    const steady = -0.5 * bodyRoll, turn = Math.sign(breath) * (F.headlift ? 40 : 78) * D - bodyRoll;
    m.head.rotation.x = clamp(lerp(steady, turn, Math.abs(breath)), -70 * D, 70 * D) + 1.5 * D * noise(3 * st, 41);
    m.head.rotation.y = -24 * D * lift - (P.head ?? 5) * D;
    showGaze(m, head);

    // Both arms keep the same timing; only the lopsided right arm's shape and grip change.
    const PRs = strokeParams(P, 'R'), PL = strokeParams(P, 'L'), PR = F.lopsided ? lopsided(PRs) : PRs;
    const right = arm(underwater(strokePhase(rightArm, PRs), PRs), PR, F);
    const left = arm(underwater(strokePhase(leftArm, PL), PL), PL, F);
    m.pace = {R: right.pace, L: left.pace};
    right.held = rightHeld;
    left.held = leftHeld;
    if (F.lopsided) right.load *= CONFIG.lopsidedCatch;  // the weak arm feels light
    vary(right, st, 1);
    vary(left, st + 0.5, 5);
    shapeHands(m, P);
    showPaddles(m, P);
    const slipness = slipShare(PL), slipR = slipShare(PR);
    m.slip = {R: slipR, L: slipness};
    m.grip = {R: gripOf(PR, slipR), L: gripOf(PL, slipness)};
    poseArm(m, 'R', right, PR, slipR, bodyRoll, pitch);
    poseArm(m, 'L', left, PL, slipness, bodyRoll, pitch);
    poseLegs(m, P, F, st, body);
    moveThroughWater(m, P, scaled, slipness, breath, previousX, resetMotion);

    showChain(m, P, F, right, left);
    showAnchor(m, P, scaled, right, left);
    showFocus(m, P, right, left);
    return [right, left, slipness];
  }

  // Catch focus (visual only): the catch is a tenth of the cycle, so this slows the clock through each
  // hand's catch and early pull, zooms the second camera in and draws the forearm against vertical.
  // catchEnv is 0 outside the window and 1 inside it, with eased edges, for the arm at clock phase p.
  const CATCH_EDGE = 0.04, CATCH_SLOW = 0.8, CATCH_ZOOM = 0.4;
  function catchEnv(p, P) {
    const path = underwater(strokePhase(p, P), P), a = CONFIG.catchStart, b = CONFIG.pull + 0.06;
    return smooth(clamp((path - (a - CATCH_EDGE)) / CATCH_EDGE, 0, 1)) * smooth(clamp(((b + CATCH_EDGE) - path) / CATCH_EDGE, 0, 1));
  }
  function catchFocusEnv(P) {
    if (!P.catchFocus || P.drill === 'catchup') return 0;
    const [r, , l] = drillArms(clockNow(), P);
    return Math.max(catchEnv(r, P), catchEnv(l, P));
  }
  const focusScratch = [];
  function makeFocus() {
    const mk = () => {
      const geo = new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({transparent: true}));
      line.frustumCulled = false; line.renderOrder = 6; line.visible = false;
      S.el.scene.add(line);
      return line;
    };
    return {fore: mk(), vert: mk(), angle: 0};
  }
  // The forearm line is teal near the default stroke's angle from vertical and reddens as the elbow drops.
  function showFocus(m, P, right, left) {
    if (!THREE) return;
    S.focus = S.focus || {};
    if (!focusScratch.length) for (let i = 0; i < 3; i++) focusScratch.push(new THREE.Vector3());
    const [e, w, d] = focusScratch;
    for (const [s, a0] of [['R', right], ['L', left]]) {
      let f = S.focus[s];
      if (!P.catchFocus && !f) continue;
      if (!f) f = S.focus[s] = makeFocus();
      const env = P.catchFocus && a0.under && P.drill !== 'catchup' ? catchEnv(s === 'R' ? drillArms(clockNow(), P)[0] : drillArms(clockNow(), P)[2], P) : 0;
      f.fore.visible = f.vert.visible = env > 0.02;
      f.angle = 0;
      if (env <= 0.02) continue;
      m['el' + s].getWorldPosition(e);
      m['wr' + s].getWorldPosition(w);
      d.subVectors(w, e);
      f.angle = Math.acos(clamp(-d.z / Math.max(1e-6, d.length()), -1, 1)) / D;
      const flat = clamp((f.angle - 70) / 30, 0, 1);  // the default pull reads about 75°, a dropped elbow about 98°
      const [r, g, b] = C.hold.map((v, i) => lerp(v, C.slip[i], flat));
      for (const [line, a, z] of [[f.fore, e, w], [f.vert, e, d.set(e.x, e.y, e.z - 0.32)]]) {
        const pos = line.geometry.attributes.position;
        pos.setXYZ(0, a.x, a.y, a.z); pos.setXYZ(1, z.x, z.y, z.z); pos.needsUpdate = true;
      }
      f.fore.material.color.setRGB(r, g, b);
      f.vert.material.color.setRGB(0.85, 0.92, 0.95);
      f.fore.material.opacity = 0.95 * env;
      f.vert.material.opacity = 0.45 * env;
    }
  }

  // Anchor (visual only): a pin fixed in the water where each hand catches, and a line from it to the
  // hand. The pin drifts back with the water, so a held hand stays on it while the body is pulled past;
  // a slipping hand slides back off it and the line stretches (teal to red).
  const ANCHOR_SLIP = 0.3;  // metres of slide at which the pin reads fully slipped
  function makeAnchor() {
    const pin = new THREE.Mesh(new THREE.SphereGeometry(0.035, 16, 12), new THREE.MeshBasicMaterial({transparent: true}));
    const geo = new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({transparent: true}));
    for (const obj of [pin, line]) { obj.frustumCulled = false; obj.renderOrder = 6; obj.visible = false; }
    S.el.scene.add(pin, line);
    return {pin, line, at: new THREE.Vector3(), tip: new THREE.Vector3(), planted: false};
  }
  const KEEP_PINS = 10, KEEP_SECONDS = 7;
  function leavePin(an) {
    S.kept = S.kept || {pins: [], meshes: []};
    const k = S.kept;
    if (!k.meshes.length) for (let i = 0; i < KEEP_PINS; i++) {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 8), new THREE.MeshBasicMaterial({transparent: true}));
      mesh.frustumCulled = false; mesh.renderOrder = 6; mesh.visible = false;
      S.el.scene.add(mesh);
      k.meshes.push(mesh);
    }
    k.pins.push({at: an.at.clone(), color: an.pin.material.color.clone(), age: 0});
    while (k.pins.length > KEEP_PINS) k.pins.shift();
  }
  function showKept(P, dt) {
    const k = S.kept;
    if (!k) return;
    if (!P.anchor || !P.anchorKeep) k.pins.length = 0;
    for (const q of k.pins) { q.at.x -= (S.flow ?? P.speed) * dt; q.age += dt; }
    while (k.pins.length && k.pins[0].age > KEEP_SECONDS) k.pins.shift();
    k.meshes.forEach((mesh, i) => {
      const q = k.pins[i];
      mesh.visible = !!q;
      if (!q) return;
      mesh.position.copy(q.at);
      mesh.material.color.copy(q.color);
      mesh.material.opacity = 0.7 * (1 - q.age / KEEP_SECONDS) ** 1.2;
    });
  }
  function showAnchor(m, P, dt, right, left) {
    if (!THREE) return;
    S.anchors = S.anchors || {};
    showKept(P, dt);
    for (const [s, a0] of [['R', right], ['L', left]]) {
      let an = S.anchors[s];
      if (!P.anchor && !an) continue;
      if (!an) an = S.anchors[s] = makeAnchor();
      const on = !!P.anchor && a0.under;
      if (!on) {
        an.slideCm = -1; an.lastSlide = undefined;
        // Keep anchor pins: the pin stays behind in the water, frozen at its colour, and fades as it drifts away.
        if (an.planted && P.anchor && P.anchorKeep) leavePin(an);
        an.planted = false; an.pin.visible = an.line.visible = false; continue;
      }
      m['wr' + s].localToWorld(an.tip.set(0.13, 0, 0));
      if (!an.planted && a0.load > 0.08) { an.at.copy(an.tip); an.planted = true; }
      if (!an.planted) continue;
      if (dt > 0) an.at.x -= (S.flow ?? P.speed) * dt;
      const slideM = Math.max(0, an.at.x - an.tip.x);
      // Hand speed through the water: how fast the hand is moving back past its pin (smoothed).
      if (dt > 0) an.speed = lerp(an.speed ?? 0, Math.max(0, (slideM - (an.lastSlide ?? slideM)) / dt), Math.min(1, dt * 8));
      an.lastSlide = slideM;
      const slide = clamp(slideM / ANCHOR_SLIP, 0, 1);
      const [r, g, b] = C.hold.map((v, i) => lerp(v, C.slip[i], slide));
      an.pin.position.copy(an.at);
      an.pin.material.color.setRGB(r, g, b);
      an.line.material.color.setRGB(r, g, b);
      an.pin.material.opacity = 0.95;
      an.line.material.opacity = 0.8;
      const pos = an.line.geometry.attributes.position;
      pos.setXYZ(0, an.at.x, an.at.y, an.at.z);
      pos.setXYZ(1, an.tip.x, an.tip.y, an.tip.z);
      pos.needsUpdate = true;
      an.pin.visible = an.line.visible = true;
      an.slide = slide;
      an.slideCm = Math.max(0, an.at.x - an.tip.x) * 100;
    }
    showAnchorCard(P, right, left);
  }

  // The Anchor card: body speed against the pulling hand's speed through the water, with a plain verdict.
  const ANCHOR_BAR = 2.5;  // m/s at which a bar is full
  function showAnchorCard(P, right, left) {
    const card = find('anchorCard', '.lc-anchor-card');
    if (!card) return;
    card.classList.toggle('on', !!P.anchor);
    if (!P.anchor) return;
    const pulling = ['R', 'L'].map(s => [S.anchors?.[s], s === 'R' ? right : left]).filter(([an, a]) => an?.planted && a.under);
    const body = Math.max(0, S.flow ?? P.speed);
    const bar = (key, speed, colour) => {
      const fill = find(key + 'Bar', `.lc-anchor-${key} .lc-anchor-fill`), val = find(key + 'Val', `.lc-anchor-${key} .lc-anchor-value`);
      if (fill) { fill.style.transform = `scaleX(${clamp(speed / ANCHOR_BAR, 0, 1).toFixed(2)})`; fill.style.background = colour; }
      if (val) val.textContent = speed.toFixed(2) + ' m/s';
    };
    let verdict = 'Waiting for a hand to catch…', hand = 0, ratio = 0;
    if (pulling.length) {
      const [an] = pulling.reduce((a, b) => (b[1].load > a[1].load ? b : a));
      hand = an.speed ?? 0;
      ratio = body > 0.05 ? clamp(hand / body, 0, 1) : 0;
      verdict = ratio < 0.08 ? 'Hand parked in the water: the body is pulled past it.'
        : ratio < 0.4 ? 'Hand creeping back: part of the pull is just moving water.'
          : 'Hand slides back nearly as fast as you move: no anchor, mostly pushing water.';
    }
    const [hr, hg, hb] = C.hold.map((v, i) => Math.round(255 * lerp(v, C.slip[i], clamp(ratio * 1.6, 0, 1))));
    bar('body', body, 'rgb(150, 190, 220)');
    bar('hand', hand, `rgb(${hr}, ${hg}, ${hb})`);
    setText('anchorVerdict', '.lc-anchor-verdict', verdict);
  }

  // Cross-body link (visual only): a band from each shoulder to the opposite hip that loads as that
  // hand catches, and a pulse that runs up it from the opposite leg's downbeat: kick, hips turn, the
  // catch takes the load. How well it connects follows the drive and the faults that break the chain.
  const chainScratch = [];
  // How well the core joins the pull to the body (0–1): the drive and the faults that break the chain.
  function coreLink(P, F) {
    return clamp((0.35 + 0.65 * P.drive) * (0.25 + 0.75 * (P.core ?? 1)) * (F.flathips ? 0.35 : 1) * (F.samesidekick ? 0.35 : 1)
      * (F.crossover ? 0.6 : 1) * (F.snaking ? 0.6 : 1) * (F.earlyroll ? 0.6 : 1) * (F.kneekick ? 0.6 : 1), 0, 1);
  }
  function showChain(m, P, F, right, left) {
    for (const s of ['R', 'L']) m['chain' + s].visible = m['chainPulse' + s].visible = !!P.chain;
    if (!P.chain) return;
    if (!chainScratch.length) for (let i = 0; i < 3; i++) chainScratch.push(new THREE.Vector3());
    const [a, b, up] = chainScratch;
    const link = coreLink(P, F);
    const col = C.hold.map((v, i) => lerp(C.slip[i], v, link));
    for (const [s, other, a0] of [['R', 'L', right], ['L', 'R', left]]) {
      const band = m['chain' + s], pulse = m['chainPulse' + s];
      const load = clamp(a0.under ? a0.load : 0, 0, 1);
      // A pulse that reaches a hand out of the water has nothing to drive: it fades.
      const pr = m.kickPulse?.[other] ?? -1, env = pr >= 0 ? Math.sin(Math.PI * pr) : 0;
      const meets = a0.under ? 1 : 0.2;
      m['sh' + s].getWorldPosition(a);
      m['leg' + other].getWorldPosition(b);
      pulse.position.copy(b).lerp(a, smooth(clamp(pr, 0, 1)));
      pulse.scale.setScalar(0.7 + 0.6 * env * link);
      pulse.material.color.setRGB(col[0], col[1], col[2]);
      pulse.material.opacity = clamp(env * meets * (0.35 + 0.6 * link), 0, 0.95);
      b.sub(a);
      const len = b.length();
      band.position.copy(a).addScaledVector(b, 0.5);
      band.quaternion.setFromUnitVectors(up.set(0, 1, 0), b.normalize());
      // The band thickens with the hand's load and snaps a little thicker as the pulse passes.
      const thick = 0.6 + 1.2 * load * link + 0.7 * env * meets * link;
      band.scale.set(thick, len, thick);
      band.material.color.setRGB(col[0], col[1], col[2]);
      band.material.opacity = clamp(0.3 + 0.6 * Math.max(load, 0.6 * env * meets) * (0.4 + 0.6 * link), 0, 0.9);
    }
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
    if (!externalClock) updateHud(right, left, slipness);
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
      S.phase = seekPhase(clamp((event.clientX - rect.left) / rect.width, 0, 0.999), S.params);
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
        S.phase = seekPhase(e.key === 'Home' ? 0 : 0.999, S.params);
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
      // A new drill moves the arms at once: restart trails, splashes and the motion response cleanly.
      if (S.params && params.drill !== S.params.drill) S.trailReset = true;
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
