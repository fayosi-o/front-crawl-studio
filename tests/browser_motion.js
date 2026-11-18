// From this directory: playwright-cli run-code --filename=browser_motion.js.
async page => {
  const view = await page.context().newPage();
  const errors = [];
  view.on('pageerror', error => errors.push(error.message));
  await view.setViewportSize({width: 1440, height: 1000});
  await view.addInitScript(() => {
    let engine;
    Object.defineProperty(window, 'LongCatch', {
      configurable: true,
      get: () => engine,
      set(value) {
        engine = value;
        const start = value.start;
        value.start = (...args) => { window.__motionStart = args; return start(...args); };
        const set = value.set;
        value.set = params => {
          window.__motionParams = params;
          window.__motionUpdates = (window.__motionUpdates || 0) + 1;
          return set(params);
        };
      },
    });
    let race;
    Object.defineProperty(window, 'LongCatchRace', {
      configurable: true,
      get: () => race,
      set(value) {
        race = value;
        const start = value.start, set = value.set;
        value.start = (scenes, config) => { window.__raceConfig = config; return start(scenes, config); };
        value.set = config => { window.__raceConfig = config; return set(config); };
      },
    });
  });
  try {
    await view.goto('http://127.0.0.1:8080/');
    await view.waitForFunction(() => window.__motionStart && window.LongCatch.ready());
    const presets = [];
    for (const name of ['Long light', 'Compact connected', 'Short slipping', 'Long power']) {
      const before = await view.evaluate(() => window.__motionUpdates || 0);
      await view.getByRole('button', {name, exact: true}).click();
      await view.waitForFunction(n => window.__motionUpdates > n, before);
      presets.push(await view.evaluate(() => window.__motionParams));
    }
    await view.evaluate(() => {
      window.LongCatch.setActive(false);
      window.LongCatch.reset();
      const [id, ids, params] = window.__motionStart;
      window.__motionEngine = window.createLongCatchEngine({externalClock: true});
      window.__motionEngine.start(id, ids, {...params, playing: false});
    });
    await view.waitForFunction(() => window.__motionEngine.ready());
    const result = await view.evaluate(presets => {
      const assert = (ok, message) => { if (!ok) throw Error(message); };
      const [id, ids, defaults] = window.__motionStart;
      const scene = getElement(id), engine = window.__motionEngine;
      const body = scene.objects.get(ids.chest).mesh.parent;
      const buoy = scene.objects.get(ids.buoys[0]).mesh;
      engine.reset();
      const origin = body.position.clone();
      const params = {...defaults, playing: false, trail: 'off', pressure: false};
      const pose = () => [...body.position.toArray(), ...body.quaternion.toArray(), buoy.position.x];
      function run(patch = {}, fps = 60, seconds = 9) {
        engine.set({...params, ...patch});
        engine.reset();
        let last = buoy.position.x, x = body.position.x, distance = 0, speedMin = Infinity, speedMax = 0;
        let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
        let pixelMin = Infinity, pixelMax = -Infinity, maxJump = 0;
        let heightMin = Infinity, heightMax = -Infinity, heightSum = 0, samples = 0, maxLegAngle = 0;
        const previous = body.position.clone();
        for (let i = 0; i < seconds * fps; i++) {
          engine.advance(1 / fps);
          const dx = ((last - buoy.position.x + 13.5) % 9) - 4.5 + body.position.x - x;
          distance += dx;
          last = buoy.position.x; x = body.position.x;
          maxJump = Math.max(maxJump, previous.distanceTo(body.position));
          previous.copy(body.position);
          assert(pose().every(Number.isFinite), 'Non-finite swimmer transform');
          assert(Math.abs(body.position.y) <= 0.181, 'Swimmer left the visual lane window');
          for (const side of ['R', 'L']) {
            for (const joint of ['leg', 'knee']) {
              maxLegAngle = Math.max(maxLegAngle, Math.abs(scene.objects.get(ids[joint + side]).mesh.rotation.y));
            }
          }
          if (i > 3 * fps) {
            heightSum += body.position.z; samples++;
            speedMin = Math.min(speedMin, dx * fps); speedMax = Math.max(speedMax, dx * fps);
            xMin = Math.min(xMin, x); xMax = Math.max(xMax, x);
            yMin = Math.min(yMin, body.position.y); yMax = Math.max(yMax, body.position.y);
            heightMin = Math.min(heightMin, body.position.z); heightMax = Math.max(heightMax, body.position.z);
            const pixel = body.position.clone().project(scene.camera).x * scene.$el.clientWidth / 2;
            pixelMin = Math.min(pixelMin, pixel); pixelMax = Math.max(pixelMax, pixel);
          }
        }
        return {distance, speedMin, speedMax, xTravel: xMax - xMin, yTravel: yMax - yMin,
          heightTravel: heightMax - heightMin, meanHeight: heightSum / samples,
          screenTravel: pixelMax - pixelMin, maxJump, maxLegAngle, end: pose()};
      }
      const clean = run();
      assert(clean.speedMax - clean.speedMin > 0.04, 'Pulls do not change forward speed');
      assert(clean.xTravel > 0.02 && clean.screenTravel > 4, 'Forward reaction is not visually readable');
      assert(clean.heightTravel > 0.0005 && clean.heightTravel < 0.05, 'Buoyancy reaction missing or excessive');
      assert(clean.maxJump < 0.03, 'Body reaction jumps between frames');
      const cross = run({faults: ['crossover']});
      assert(cross.yTravel > 0.003, 'Crossover does not move the body across the pool');
      const slip = run({slip: 1, catch: 0.1});
      assert(slip.distance < clean.distance, 'Poor grip does not reduce visual propulsion');
      const sunk = run({faults: ['sinking']});
      assert(sunk.distance < clean.distance, 'Sinking legs do not increase resistance');
      const kicks = [2, 4, 6].map(beats => ({
        beats, still: run({kick: 0, beats}), moderate: run({kick: 0.45, beats}),
        strong: run({kick: 1, beats}), knees: run({kick: 1, beats, faults: ['kneekick']}),
      }));
      for (const {beats, still, moderate, strong, knees} of kicks) {
        assert(still.maxLegAngle === 0, `${beats}-beat legs still kick at zero amplitude`);
        assert(moderate.distance > still.distance * 1.003, `${beats}-beat downbeats add no readable propulsion`);
        for (const active of [moderate, strong]) {
          assert(Math.abs(active.distance / still.distance - 1) < 0.05, 'Kick response overwhelms arm propulsion');
          assert(active.maxJump < 0.03 && active.heightTravel < 0.05, 'Kick reaction is excessive');
        }
        assert(strong.meanHeight > still.meanHeight + 0.0001, 'Kick changes have no balance response');
        assert(knees.distance < strong.distance, 'Bent-knee kick does not lose efficiency');
      }
      const slow = run({}, 30), fast = run({}, 120);
      assert(Math.abs(slow.distance - fast.distance) / fast.distance < 0.01, 'Frame rate changes travel by over 1%');
      const kickSlow = run({kick: 1, beats: 6}, 30), kickFast = run({kick: 1, beats: 6}, 120);
      assert(Math.abs(kickSlow.distance - kickFast.distance) / kickFast.distance < 0.01,
        'Fast kicks depend on frame rate');
      const accelerated = run({}, 2.5, 8), normal = run({}, 120, 8);
      assert(Math.abs(accelerated.distance - normal.distance) / normal.distance < 0.01, '4x race frames change travel');
      const catchDelay = glide => {
        let lo = 0, hi = 0.3;
        for (let i = 0; i < 32; i++) {
          const mid = (lo + hi) / 2;
          if (mid - glide * Math.sin(Math.PI * mid / 0.3) ** 2 < 0.12) lo = mid;
          else hi = mid;
        }
        return (lo + hi) / 2 - 0.12;
      };
      for (const preset of presets) {
        run(preset, 30, 6);
        for (const frontGlide of [-0.08, 0.08]) run({...preset, frontGlide, catchDelay: catchDelay(frontGlide)}, 30, 6);
      }
      run({faults: ['crossover', 'overrotation', 'overreach', 'flathips', 'sinking', 'snaking', 'kneekick', 'rushing'],
        rush: 0.72}, 30, 12);
      run({}, 30, 60);
      const paused = JSON.stringify(pose());
      for (let i = 0; i < 10; i++) engine.advance(0);
      assert(JSON.stringify(pose()) === paused, 'Paused swimmer drifts');
      engine.reset();
      assert(Math.abs(body.position.x) < 1e-10 && Math.abs(body.position.y) < 1e-10, 'Reset retains travel');
      assert(Math.abs(body.position.z - origin.z) < 1e-10, 'Reset retains buoyancy reaction');
      run({}, 60, 2);
      const phase = engine.step(0);
      assert(Math.abs(phase - 2 / (120 / params.rate)) < 1e-8, 'Water reaction changed the stroke clock');
      const kickSummary = kicks.map(({beats, still, moderate, strong, knees}) => ({
        beats, distances: [still.distance, moderate.distance, strong.distance, knees.distance],
        balanceChange: strong.meanHeight - still.meanHeight,
      }));
      return {clean, cross, slip, sunk, kicks: kickSummary,
        frameRateDistance: [slow.distance, fast.distance], checks: 'passed'};
    }, presets);
    await view.reload();
    await view.waitForFunction(() => window.__motionStart && window.LongCatch.ready());
    await view.getByRole('tab', {name: 'Race', exact: true}).click();
    await view.locator('.lc-race-board').waitFor({state: 'visible'});
    await view.getByRole('button', {name: '25 m', exact: true}).click();
    await view.waitForFunction(() => window.__raceConfig?.distance === 25);
    const expected = await view.evaluate(() => Math.max(...window.__raceConfig.lanes.map(lane => lane.finishTime)));
    await view.getByRole('button', {name: '4x', exact: true}).click();
    await view.getByRole('button', {name: 'Start race', exact: true}).click();
    await view.waitForFunction(() => document.querySelector('.lc-race-board').dataset.status === 'Finished',
      undefined, {timeout: 30000});
    const elapsed = await view.locator('.lc-race-board').getAttribute('data-elapsed');
    if (Math.abs(Number(elapsed) - expected) > 1e-8) throw Error('Visual reactions changed race finish time');
    for (const lane of ['a', 'b']) {
      const metres = await view.locator(`.lc-race-track-${lane}`).getAttribute('aria-valuenow');
      if (Number(metres) !== 25) throw Error('Race distance changed');
    }
    if (errors.length) throw Error(errors.join('\n'));
    return {...result, raceFinish: Number(elapsed)};
  } finally {
    await view.close();
  }
}
