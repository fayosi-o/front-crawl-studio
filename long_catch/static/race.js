// One race clock drives independent instances of the studio's swimmer engine.
window.LongCatchRace = (() => {
  const R = {engines: [], config: null, elapsed: 0, speed: 1, running: false, active: false, last: null, ready: false};
  const nodes = {};
  const node = selector => nodes[selector] || (nodes[selector] = document.querySelector(`.lc-race ${selector}`));
  const text = (selector, value) => {
    const el = node(selector);
    if (el && el.textContent !== value) el.textContent = value;
  };
  const duration = seconds => {
    const centiseconds = Math.round(seconds * 100), minutes = Math.floor(centiseconds / 6000);
    const rest = ((centiseconds % 6000) / 100).toFixed(2);
    return minutes ? `${minutes}:${rest.padStart(5, '0')}` : `${rest} s`;
  };
  const endTime = () => Math.max(...R.config.lanes.map(lane => lane.finishTime));
  const finished = () => R.elapsed >= endTime();

  function drawHud() {
    const lanes = R.config.lanes, done = finished();
    const status = !R.ready ? 'Loading lanes' : done ? 'Finished' : R.running ? 'Racing' : R.elapsed ? 'Paused' : 'Ready';
    const root = node('.lc-race-board');
    if (!root) return;
    root.dataset.status = status;
    root.dataset.elapsed = R.elapsed;
    text('.lc-race-status', status);
    text('.lc-race-clock', duration(R.elapsed));
    text('.lc-race-play-label', done ? 'Race again' : R.running ? 'Pause race' : R.elapsed ? 'Resume race' : 'Start race');
    node('.lc-race-play').disabled = !R.ready;
    const best = Math.min(...lanes.map(lane => lane.finishTime));
    lanes.forEach((lane, i) => {
      const key = i ? 'b' : 'a', time = Math.min(R.elapsed, lane.finishTime);
      const arrived = R.elapsed >= lane.finishTime;
      const metres = arrived ? R.config.distance : Math.min(R.config.distance, time * lane.params.speed);
      const percent = 100 * metres / R.config.distance;
      const track = node(`.lc-race-track-${key}`);
      track.setAttribute('aria-valuenow', metres.toFixed(2));
      track.setAttribute('aria-valuemax', R.config.distance);
      node(`.lc-race-fill-${key}`).style.width = `${percent}%`;
      text(`.lc-race-metres-${key}`, `${metres.toFixed(1)} / ${R.config.distance} m`);
      text(`.lc-race-time-${key}`, duration(time));
      const tied = lanes.length === 2 && Math.abs(lanes[0].finishTime - lanes[1].finishTime) < 0.005;
      const result = arrived ? (lanes.length === 1 ? 'Finished' : tied ? 'Tie' : lane.finishTime === best ? '1st' : '2nd') : '';
      text(`.lc-race-place-${key}`, result);
    });
    let summary = 'Same start. Independent strokes. Follow cameras keep both swimmers in view.';
    if (done) {
      if (lanes.length === 1) summary = `Swimmer A finished ${R.config.distance} m in ${duration(best)}.`;
      else {
        const gap = Math.abs(lanes[0].finishTime - lanes[1].finishTime);
        summary = gap < 0.005 ? 'Dead heat: both setups finish together.'
          : `Swimmer ${lanes[0].finishTime < lanes[1].finishTime ? 'A' : 'B'} wins by ${duration(gap)}.`;
      }
    } else if (R.elapsed > 0 && lanes.length === 2) {
      const positions = lanes.map(lane => Math.min(R.config.distance, R.elapsed * lane.params.speed));
      const gap = Math.abs(positions[0] - positions[1]);
      summary = gap < 0.05 ? 'Level: both swimmers are together.'
        : `Swimmer ${positions[0] > positions[1] ? 'A' : 'B'} leads by ${gap.toFixed(1)} m.`;
    }
    text('.lc-race-summary', summary);
  }

  function reset() {
    R.elapsed = 0; R.running = false; R.last = null;
    R.engines.forEach(engine => engine.reset());
    drawHud();
  }

  function frame(t) {
    requestAnimationFrame(frame);
    if (!R.active || document.hidden || !R.config) { R.last = null; return; }
    if (!R.ready) {
      R.ready = R.engines.slice(0, R.config.lanes.length).every(engine => engine.ready());
      if (!R.ready) { R.last = null; return; }
      R.engines.forEach(engine => engine.reset());
    }
    const dt = R.last === null ? 0 : Math.min(0.1, (t - R.last) / 1000);
    R.last = t;
    if (R.running) {
      const next = Math.min(endTime(), R.elapsed + dt * R.speed);
      R.config.lanes.forEach((lane, i) => {
        R.engines[i].advance(Math.min(next, lane.finishTime) - Math.min(R.elapsed, lane.finishTime));
      });
      R.elapsed = next;
      if (finished()) R.running = false;
    }
    drawHud();
  }

  function set(config) {
    R.config = config; R.ready = false;
    config.lanes.forEach((lane, i) => R.engines[i].set(lane.params));
    reset();
    R.engines.forEach(engine => engine.fit());
  }

  function toggle() {
    if (!R.ready || !R.active) return;
    if (finished()) reset();
    R.running = !R.running;
    R.last = null;
    drawHud();
  }

  return {
    start(scenes, config) {
      if (R.engines.length) return;
      R.engines = scenes.map((scene, i) => {
        const engine = window.createLongCatchEngine({root: `.lc-race-lane-${i ? 'b' : 'a'}`, externalClock: true});
        engine.start(scene.id, scene.ids, config.lanes[i]?.params || config.lanes[0].params);
        return engine;
      });
      set(config);
      R.active = true;
      requestAnimationFrame(frame);
      document.addEventListener('keydown', e => {
        if (!R.active || e.code !== 'Space' || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
        if (document.activeElement?.closest('input, textarea, button, [role="slider"], [role="tab"], [role="combobox"], [contenteditable]')) return;
        e.preventDefault();
        node('.lc-race-play').click();
      });
    },
    set, toggle, reset,
    setSpeed(speed) { R.speed = speed; R.last = null; },
    setActive(active) {
      R.active = active; R.running = false; R.last = null;
      if (active) R.engines.forEach(engine => engine.fit());
      if (R.config) drawHud();
    },
    resetCamera() { R.engines.forEach(engine => engine.resetCamera()); },
  };
})();
