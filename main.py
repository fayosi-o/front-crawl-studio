"""Long Catch: a silent visual prototype of front-crawl stroke shape.

Run with ``python main.py`` and open http://127.0.0.1:8080.
All numbers and muscle colours are coaching estimates, not measured data.
"""

import json
import math
from dataclasses import replace

from nicegui import ui

from long_catch.model import (
    EMPHASES,
    PHASE_LABELS,
    PRESETS,
    SETTING_RANGES,
    ViewState,
    clamp,  # noqa: F401  (build-prompt hook)
    cycle_duration,  # noqa: F401  (build-prompt hook)
    estimate_metrics,  # noqa: F401  (build-prompt hook)
    format_duration,
)

BG = '#08141a'
PANEL = '#123038'
TEXT = '#e7f0ea'
MUTED = '#9cb0ac'
HOLD = '#3dbea5'
SLIP = '#e36b4f'
SKIN = '#d8bfa3'
SUIT = '#1f5563'
PATCH = '#f2c14e'
WATER = '#2a8fa8'

# Browser-side pose loop. Python owns settings; the browser only animates.
ENGINE_JS = (
    r"""
window.LongCatch = window.LongCatch || (() => {
  const S = { sceneId: null, ids: null, params: null, phase: 0, offset: 0, last: null, m: null, running: false };
  const D = Math.PI / 180;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = t => t * t * (3 - 2 * t);
  const bump = (p, a, b) => (p > a && p < b ? Math.sin(Math.PI * (p - a) / (b - a)) : 0);
  const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  const C = { hold: rgb('__HOLD__'), slip: rgb('__SLIP__'), skin: rgb('__SKIN__') };
  const EMPHASIS = {
    back: [1, 0, 0], triceps: [0, 1, 0], core: [0, 0, 1], balanced: [0.55, 0.55, 0.55],
  };
  const PHASES = __PHASES__;

  function keyed(p, keys) {
    for (let i = 0; i < keys.length - 1; i++) {
      const [p0, v0] = keys[i], [p1, v1] = keys[i + 1];
      if (p <= p1) return lerp(v0, v1, smooth(clamp((p - p0) / (p1 - p0), 0, 1)));
    }
    return keys[keys.length - 1][1];
  }

  function arm(p, P) {
    const c = P.catch, s = P.slip, L = P.length;
    const exit = P.exit;
    const midRec = exit + (1 - exit) * 0.5;
    // Shoulder pitch: 0 = reaching forward, 90 = straight down, 180 = along the body.
    const pitch = keyed(p, [
      [0, 8], [0.12, 3], [0.30, lerp(44, 18, c) + 34 * s],
      [0.62, 100 + 10 * L + 8 * s], [exit, lerp(126, 162, L)], [midRec, 250], [1, 368],
    ]);
    const elbow = keyed(p, [
      [0, 8], [0.12, 0], [0.30, lerp(10, 74, c) * (1 - 0.5 * s)],
      [0.62, lerp(10, 55, c) * (1 - 0.4 * s)], [exit, 6], [midRec, 125], [1, 8],
    ]);
    const under = p < exit;
    const abd = under ? 6 * Math.sin(Math.PI * p / exit) : 55 * Math.sin(Math.PI * (p - exit) / (1 - exit));
    const wrist = under ? -48 * s * bump(p, 0.08, exit) + 12 * (1 - s) * bump(p, 0.12, 0.45) : 15;
    const stage = p < 0.12 ? 0 : p < 0.30 ? 1 : p < 0.62 ? 2 : p < exit ? 3 : 4;
    return {
      pitch: pitch * D, elbow: elbow * D, abd: abd * D, wrist: wrist * D, under, stage,
      back: bump(p, 0.10, 0.64), triceps: bump(p, 0.50, exit + 0.04),
    };
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
    el.$el.style.width = '100%';
    el.$el.style.height = '100%';
    S.el = el;
    S.m = m;
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

  function paint(mesh, under, slipness) {
    const col = under ? C.hold.map((v, i) => lerp(v, C.slip[i], slipness)) : C.skin;
    mesh.material.color.setRGB(col[0], col[1], col[2]);
  }

  function patch(mesh, value) {
    mesh.material.opacity = clamp(Math.sqrt(Math.max(0, value)) * 0.85, 0, 0.85);
    mesh.visible = value > 0.02;
  }

  function poseArm(m, side, a, P, slipness) {
    const sgn = side === 'R' ? 1 : -1;
    m['sh' + side].rotation.set(sgn * a.abd, a.pitch, 0);
    m['el' + side].rotation.set(0, a.elbow, 0);
    m['wr' + side].rotation.set(0, a.wrist, 0);
    paint(m['fa' + side], a.under, slipness);
    paint(m['ha' + side], a.under, slipness);
  }

  function frame(t) {
    requestAnimationFrame(frame);
    if (document.hidden || !S.params) { S.last = null; return; }
    const dt = S.last === null ? 0 : Math.min(0.1, (t - S.last) / 1000);
    S.last = t;
    if (!resolve()) return;
    const P = S.params, m = S.m;
    if (P.playing) {
      S.phase = (S.phase + dt / (120 / P.rate)) % 1;
      S.offset += P.speed * dt;
    }
    const right = arm(S.phase, P), left = arm((S.phase + 0.5) % 1, P);
    const slipness = smooth(clamp((0.75 * P.slip + 0.5 * (1 - P.catch) - 0.25) / 0.3, 0, 1));
    poseArm(m, 'R', right, P, slipness);
    poseArm(m, 'L', left, P, slipness);

    // Body roll: positive = right shoulder down. Connected drive lets the hips lead.
    const roll = P.roll * D, w = 2 * Math.PI;
    const lead = 0.07 * P.drive - 0.05 * (1 - P.drive);
    m.chest.rotation.set(roll * Math.cos(w * (S.phase - 0.1)), 0, 0);
    m.pelvis.rotation.set(roll * (0.3 + 0.6 * P.drive) * Math.cos(w * (S.phase - 0.1 + lead)), 0, 0);

    const kick = w * 3 * S.phase;
    m.legR.rotation.set(0, 0.2 * Math.sin(kick), 0);
    m.legL.rotation.set(0, 0.2 * Math.sin(kick + Math.PI), 0);
    m.kneeR.rotation.set(0, 0.35 * Math.max(0, Math.sin(kick + 1.0)), 0);
    m.kneeL.rotation.set(0, 0.35 * Math.max(0, Math.sin(kick + Math.PI + 1.0)), 0);

    const [eb, et, ec] = EMPHASIS[P.emphasis] || EMPHASIS.balanced;
    const k = P.intensity;
    const core = Math.abs(Math.sin(w * (S.phase - 0.1 + lead))) * (0.35 + 0.65 * P.drive);
    patch(m.backR, eb * k * right.back);
    patch(m.backL, eb * k * left.back);
    patch(m.triR, et * k * right.triceps);
    patch(m.triL, et * k * left.triceps);
    patch(m.core, ec * k * core);
    patch(m.hipR, ec * k * core);
    patch(m.hipL, ec * k * core);

    m.buoys.forEach((b, i) => {
      const span = 9;
      b.position.x = ((((m.basePos[i] - S.offset + 4.5) % span) + span) % span) - 4.5;
    });

    const text = 'Right arm: ' + PHASES[right.stage] + '  ·  Left arm: ' + PHASES[left.stage];
    if (text !== S.labelText) {
      if (!S.label || !S.label.isConnected) S.label = document.querySelector('.lc-root .lc-phase');
      if (S.label) { S.label.textContent = text; S.labelText = text; }
    }
  }

  return {
    start(sceneId, ids, params) {
      S.sceneId = sceneId; S.ids = ids; S.params = params; S.m = null; S.last = null;
      if (!S.running) {
        S.running = true;
        requestAnimationFrame(frame);
        window.addEventListener('resize', () => setTimeout(fitCamera, 50));
      }
    },
    set(params) { S.params = Object.assign({}, S.params, params); },
  };
})();
""".replace('__HOLD__', HOLD)
    .replace('__SLIP__', SLIP)
    .replace('__SKIN__', SKIN)
    .replace('__PHASES__', json.dumps(list(PHASE_LABELS.values())))
)

LAYOUT_CSS = """
.nicegui-content { padding: 0 !important; }
.lc-root { display: flex; width: 100%; height: 100vh; }
.lc-stage { position: relative; flex: 1 1 auto; min-width: 0; min-height: 0; overflow: hidden; }
.lc-panel { flex: 0 0 340px; width: 340px; height: 100vh; overflow-y: auto; }
@media (max-width: 760px) {
  .lc-root { flex-direction: column; height: auto; }
  .lc-stage { flex: none; height: 62vh; }
  .lc-panel { flex: none; width: 100%; height: auto; }
}
"""


def capsule_x(radius: float, length: float, color: str, start: float = 0.0, direction: int = 1):
    """Capsule whose axis runs along local x from ``start``; NiceGUI capsules default to the y axis."""
    return (
        ui.scene.capsule(radius, length, 6, 14)
        .material(color)
        .rotate(0, 0, -direction * math.pi / 2)
        .move(start + direction * length / 2, 0, 0)
    )


def build_swimmer(ids: dict) -> None:
    """Prone swimmer: head towards +x, z up, right side towards -y."""

    def reg(name, obj):
        ids[name] = obj.id
        return obj

    def patch(obj):
        return obj.material(PATCH, 0.0)

    reg('water', ui.scene.plane(10, 4).material(WATER, 0.16, 'both').move(-0.5, 0, 0.0))

    with ui.scene.group().move(0, 0, -0.06):
        with reg('chest', ui.scene.group()):
            ui.scene.cylinder(0.19, 0.13, 0.62, 24).material(SUIT).rotate(0, 0, -math.pi / 2).scale(1.3, 1, 0.75)
            ui.scene.capsule(0.075, 0.40, 6, 14).material(SKIN).move(0.27, 0, 0)
            capsule_x(0.05, 0.08, SKIN, start=0.33)
            ui.scene.sphere(0.11, 24, 16).material(SKIN).scale(1.2, 0.92, 1.0).move(0.52, 0, 0.02)
            ui.scene.sphere(0.112, 24, 16).material(SUIT).scale(1.0, 0.95, 0.9).move(0.5, 0, 0.05)
            reg('backR', patch(ui.scene.sphere(0.12, 20, 12)).scale(1.6, 0.55, 0.7).move(0.06, -0.16, 0.06))
            reg('backL', patch(ui.scene.sphere(0.12, 20, 12)).scale(1.6, 0.55, 0.7).move(0.06, 0.16, 0.06))
            for side, y in (('R', -0.235), ('L', 0.235)):
                with reg('sh' + side, ui.scene.group().move(0.27, y, 0)):
                    capsule_x(0.056, 0.26, SKIN)
                    reg(
                        'tri' + side,
                        patch(ui.scene.capsule(0.042, 0.16, 6, 12)).rotate(0, 0, -math.pi / 2).move(0.13, 0, -0.03),
                    )
                    with reg('el' + side, ui.scene.group().move(0.28, 0, 0)):
                        reg('fa' + side, capsule_x(0.045, 0.24, SKIN))
                        with reg('wr' + side, ui.scene.group().move(0.27, 0, 0)):
                            reg('ha' + side, ui.scene.box(0.15, 0.09, 0.028).material(SKIN).move(0.075, 0, 0))

        with reg('pelvis', ui.scene.group().move(-0.36, 0, 0)):
            ui.scene.cylinder(0.135, 0.15, 0.22, 24).material(SUIT).rotate(0, 0, -math.pi / 2).scale(1.3, 1, 0.8)
            reg(
                'core',
                patch(ui.scene.cylinder(0.15, 0.15, 0.1, 24))
                .rotate(0, 0, -math.pi / 2)
                .scale(1.3, 1, 0.9)
                .move(0.13, 0, 0),
            )
            reg('hipR', patch(ui.scene.sphere(0.075, 16, 10)).scale(1.3, 0.6, 1).move(-0.02, -0.16, 0.02))
            reg('hipL', patch(ui.scene.sphere(0.075, 16, 10)).scale(1.3, 0.6, 1).move(-0.02, 0.16, 0.02))
            for side, y in (('R', -0.085), ('L', 0.085)):
                with reg('leg' + side, ui.scene.group().move(-0.08, y, 0)):
                    capsule_x(0.068, 0.36, SKIN, direction=-1)
                    with reg('knee' + side, ui.scene.group().move(-0.38, 0, 0)):
                        capsule_x(0.05, 0.34, SKIN, direction=-1)
                        with ui.scene.group().move(-0.37, 0, 0):
                            ui.scene.box(0.17, 0.075, 0.05).material(SKIN).move(-0.06, 0, 0)

    buoys = []
    for i in range(18):
        color = HOLD if i % 2 else TEXT
        buoys.append(ui.scene.sphere(0.045, 12, 8).material(color).move(-4.25 + i * 0.5, 1.2, 0.02).id)
    ids['buoys'] = buoys


@ui.page('/')
async def index() -> None:
    ui.query('body').style(f'background:{BG}; color:{TEXT}; margin:0')
    ui.colors(primary=HOLD)
    ui.add_body_html(f'<script>{ENGINE_JS}</script>')
    ui.add_head_html(f'<style>{LAYOUT_CSS}</style>')

    view = ViewState()
    ids: dict = {}
    sliders: dict = {}
    values: dict = {}
    stats: dict = {}
    applying_preset = False

    def refresh() -> None:
        m = view.settings.metrics()
        holding = m['hold_quality'] >= 0.7
        color = f'color:{HOLD if holding else SLIP}'
        stats['rate'].text = f'{view.settings.rate} spm'
        stats['dps'].text = f'{m["distance_per_stroke"]:.2f} m'
        stats['dps'].style(color)
        stats['spl'].text = f'{m["strokes_per_25"]:.1f}'
        stats['t25'].text = format_duration(m['seconds_per_25'])
        stats['hold'].text = 'Hand holding water' if holding else 'Hand slipping'
        stats['hold'].style(color)
        ui.run_javascript(f'window.LongCatch && window.LongCatch.set({json.dumps(view.render_params(m))})')

    def update(**changes) -> None:
        nonlocal view
        new = replace(view, **changes)
        if new != view:
            view = new
            refresh()

    def on_slider(key: str, value: float) -> None:
        values[key].text = f'{value:.0f}{UNITS[key]}'
        if not applying_preset:
            update(settings=view.settings.with_values(**{key: int(value)}))

    def apply_preset(name: str) -> None:
        nonlocal applying_preset
        preset = PRESETS[name]
        applying_preset = True
        try:
            for key in SETTING_RANGES:
                sliders[key].value = getattr(preset, key)
        finally:
            applying_preset = False
        update(settings=preset)

    def toggle_play() -> None:
        playing = not view.playing
        play_btn.text = 'Pause' if playing else 'Play'
        play_btn.props(f'icon={"pause" if playing else "play_arrow"}')
        update(playing=playing)

    UNITS = {'rate': ' spm', 'catch': '%', 'roll': '°', 'slip': '%', 'drive': '%'}
    LABELS = {
        'rate': 'Stroke rate',
        'catch': 'Catch quality',
        'roll': 'Body roll',
        'slip': 'Slip',
        'drive': 'Drive balance',
    }
    EMPHASIS_LABELS = {'back': 'Back', 'triceps': 'Triceps', 'core': 'Hips/core', 'balanced': 'Balanced'}
    assert set(EMPHASIS_LABELS) == set(EMPHASES)

    with ui.element('div').classes('lc-root'):
        with ui.element('div').classes('lc-stage'):
            scene = ui.scene(
                width=900,
                height=700,
                grid=False,
                background_color=BG,
                fps=60,
                camera=ui.scene.perspective_camera(fov=42),
            )
            with scene:
                build_swimmer(ids)
            scene.move_camera(0.6, -2.3, 0.3, -0.1, 0, -0.22, duration=0)
            with ui.column().classes('absolute top-4 left-5 gap-1').style('pointer-events:none'):
                ui.label('Long Catch').classes('text-2xl font-bold')
                ui.label('Estimated contribution for this modelled stroke').style(f'color:{PATCH}')
                ui.label('').classes('lc-phase text-sm').style(f'color:{MUTED}')
            with (
                ui.row().classes('absolute bottom-4 left-5 gap-4 text-xs').style(f'color:{MUTED}; pointer-events:none')
            ):
                ui.label('● holding').style(f'color:{HOLD}')
                ui.label('● slipping').style(f'color:{SLIP}')
                ui.label('● estimated muscle emphasis').style(f'color:{PATCH}')
                ui.label('Drag to orbit · scroll to zoom')

        with ui.column().classes('lc-panel p-5 gap-3 no-wrap').style(f'background:{PANEL}'):
            play_btn = ui.button('Pause', icon='pause', on_click=toggle_play).classes('w-full')

            ui.label('Presets').classes('text-xs uppercase tracking-wider').style(f'color:{MUTED}')
            with ui.grid(columns=2).classes('w-full gap-2'):
                for name in PRESETS:
                    ui.button(name, on_click=lambda n=name: apply_preset(n)).props('outline no-caps dense').classes(
                        'w-full'
                    )

            for key, (lo, hi) in SETTING_RANGES.items():
                value = getattr(view.settings, key)
                with ui.row().classes('w-full justify-between items-end -mb-2'):
                    ui.label(LABELS[key]).classes('text-sm')
                    values[key] = ui.label(f'{value}{UNITS[key]}').classes('text-sm').style(f'color:{MUTED}')
                sliders[key] = ui.slider(
                    min=lo, max=hi, step=1, value=value, on_change=lambda e, k=key: on_slider(k, e.value)
                )
            with ui.row().classes('w-full justify-between text-xs -mt-3').style(f'color:{MUTED}'):
                ui.label('arm-driven')
                ui.label('hip-connected')

            ui.label('Muscle emphasis').classes('text-xs uppercase tracking-wider').style(f'color:{MUTED}')
            ui.toggle(EMPHASIS_LABELS, value=view.emphasis, on_change=lambda e: update(emphasis=e.value)).props(
                'dense no-caps spread'
            ).classes('w-full')

            ui.label('Estimates').classes('text-xs uppercase tracking-wider').style(f'color:{MUTED}')
            with ui.grid(columns=2).classes('w-full gap-3'):
                for key, caption in (
                    ('rate', 'Stroke rate'),
                    ('dps', 'Distance / stroke (est.)'),
                    ('spl', 'Strokes / 25 m (est.)'),
                    ('t25', 'Time / 25 m (est.)'),
                ):
                    with ui.column().classes('gap-0'):
                        stats[key] = ui.label().classes('text-xl font-bold')
                        ui.label(caption).classes('text-xs').style(f'color:{MUTED}')
            stats['hold'] = ui.label().classes('text-sm font-medium')
            ui.label('Coaching estimates only — not measured, EMG, or medical data.').classes('text-xs').style(
                f'color:{MUTED}'
            )

    await ui.context.client.connected()
    ui.run_javascript(f'window.LongCatch.start({scene.id}, {json.dumps(ids)}, {json.dumps(view.render_params())})')
    refresh()


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(host='127.0.0.1', port=8080, title='Long Catch', reload=False, show=False, dark=True)
