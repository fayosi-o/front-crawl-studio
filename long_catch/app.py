"""NiceGUI page: stage overlays, transport controls, and the settings panel."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Any

from nicegui import ui

from long_catch.engine import BrowserEngine, engine_script
from long_catch.model import (
    EMPHASES,
    FAULTS,
    PHASE_LABELS,
    PLAYBACK_SPEEDS,
    PRESETS,
    SETTING_RANGES,
    Metrics,
    Phase,
    ViewState,
    format_duration,
    matching_preset,
    path_length,
    timeline_boundaries,
)
from long_catch.swimmer import SwimmerBuilder
from long_catch.theme import PALETTE, stylesheet

STEP = 0.05


@dataclass(frozen=True, slots=True)
class SliderSpec:
    key: str
    label: str
    unit: str
    hint: str
    low: str = ''
    high: str = ''


SLIDERS: tuple[SliderSpec, ...] = (
    SliderSpec('rate', 'Stroke rate', ' spm', 'Hand entries per minute. Lower rates lengthen the underwater path.'),
    SliderSpec('catch', 'Catch quality', '%', 'How early and firmly the forearm sets against the water.'),
    SliderSpec('roll', 'Body roll', '°', 'Peak rotation of the chest about the long axis.'),
    SliderSpec('slip', 'Slip', '%', 'How much the hand slides through the water instead of holding it.'),
    SliderSpec(
        'entry',
        'Entry angle',
        '°',
        'How steeply the arm extends after the hand enters. Visual only; it does not change the estimates.',
        'near surface',
        'toward floor',
    ),
    SliderSpec(
        'drive', 'Drive balance', '%', 'How much the hips lead and connect the pull.', 'arm-driven', 'hip-connected'
    ),
    SliderSpec(
        'kick',
        'Kick amplitude',
        '%',
        'Flutter-kick size. Visual only; it does not change the estimates.',
        'still legs',
        'strong flutter',
    ),
)
assert {spec.key for spec in SLIDERS} == set(SETTING_RANGES)

EMPHASIS_LABELS = {'back': 'Back', 'triceps': 'Triceps', 'core': 'Hips/core', 'balanced': 'Balanced'}
assert set(EMPHASIS_LABELS) == set(EMPHASES)

PLAYBACK_LABELS = {0.25: '¼×', 0.5: '½×', 1.0: '1×'}
assert set(PLAYBACK_LABELS) == set(PLAYBACK_SPEEDS)

FAULT_ICONS = {
    'crossover': 'compare_arrows',
    'overrotation': 'rotate_right',
    'overreach': 'front_hand',
    'flathips': 'horizontal_rule',
    'sinking': 'trending_down',
    'snaking': 'gesture',
    'kneekick': 'directions_bike',
    'rushing': 'fast_forward',
}
assert set(FAULT_ICONS) == set(FAULTS)

STATS: tuple[tuple[str, str], ...] = (
    ('rate', 'Stroke rate'),
    ('dps', 'Distance / stroke'),
    ('spl', 'Strokes / 25 m'),
    ('t25', 'Time / 25 m'),
)


def section_title(text: str) -> ui.label:
    return ui.label(text).classes('lc-section-title')


class LongCatchPage:
    """One client's page. Python owns the settings; the browser engine owns the live phase."""

    def __init__(self) -> None:
        self.view = ViewState()
        self.engine = BrowserEngine()
        self.scene_ids: dict = {}
        self.sliders: dict[str, ui.slider] = {}
        self.slider_values: dict[str, ui.label] = {}
        self.stats: dict[str, ui.label] = {}
        self.preset_buttons: dict[str, ui.button] = {}
        self.fault_buttons: dict[str, ui.button] = {}
        self._fault_layout: frozenset[str] | None = None
        self.segments: list[ui.element] = []
        self._applying_preset = False
        self._segment_layout: tuple[float, ...] = ()

    # ---- layout -------------------------------------------------------------------------------

    def build(self) -> None:
        ui.add_head_html(stylesheet())
        ui.add_body_html(engine_script())
        ui.colors(primary=PALETTE.hold)
        with ui.element('div').classes('lc-root'):
            self._build_stage()
            self._build_panel()
        self._render()

    def _build_stage(self) -> None:
        with ui.element('div').classes('lc-stage'):
            self.scene = ui.scene(
                width=900,
                height=700,
                grid=False,
                background_color=PALETTE.background,
                fps=60,
                camera=ui.scene.perspective_camera(fov=42),
            )
            with self.scene:
                self.scene_ids = SwimmerBuilder().build()
            self.scene.move_camera(0.6, -2.3, 0.3, -0.1, 0, -0.22, duration=0)

            with ui.element('div').classes('lc-hud-top'):
                with ui.element('div').classes('lc-glass lc-brand'):
                    ui.label('Long Catch').classes('lc-title')
                    ui.label('Front-crawl stroke shape · estimated muscle emphasis').classes('lc-subtitle')
                    with ui.row().classes('lc-legend'):
                        for css, text in (('hold', 'holding'), ('slip', 'slipping'), ('patch', 'emphasis')):
                            with ui.element('span').classes('lc-legend-item'):
                                ui.element('span').classes(f'lc-dot lc-dot-{css}')
                                ui.label(text)
                with ui.element('div').classes('lc-glass lc-arms'):
                    for side in ('right', 'left'):
                        with ui.element('div').classes('lc-arm'):
                            ui.label(f'{side.title()} arm').classes('lc-arm-side')
                            ui.label(Phase.ENTRY.label).classes(f'lc-arm-phase lc-arm-{side}')
            self._build_transport()

    def _build_transport(self) -> None:
        with ui.element('div').classes('lc-glass lc-dock'):
            with ui.element('div').classes('lc-timeline').props('title="Drag to scrub the right-arm cycle"'):
                for index, label in enumerate(PHASE_LABELS.values()):
                    with ui.element('div').classes(f'lc-seg lc-seg-{index}') as segment:
                        ui.label(label.split(' ')[0])
                    self.segments.append(segment)
                ui.element('div').classes('lc-timeline-marker')
            with ui.element('div').classes('lc-transport'):
                self.step_back = self._icon_button('chevron_left', 'Step back 5% (←)', lambda: self.step(-STEP))
                self.step_back.classes('lc-step-back')
                self.play_button = ui.button(icon='pause', on_click=self.toggle_play).props('round unelevated')
                self.play_button.classes('lc-play').tooltip('Play / pause (Space)')
                self.step_forward = self._icon_button('chevron_right', 'Step forward 5% (→)', lambda: self.step(STEP))
                self.step_forward.classes('lc-step-forward')
                ui.label('0%').classes('lc-cycle')
                ui.element('div').classes('lc-spacer')
                ui.toggle(PLAYBACK_LABELS, value=self.view.playback, on_change=lambda e: self.update(playback=e.value))
                self._icon_button('center_focus_strong', 'Reset camera (C)', self.engine.reset_camera).classes(
                    'lc-reset-camera'
                )

    @staticmethod
    def _icon_button(icon: str, tooltip: str, on_click) -> ui.button:
        button = ui.button(icon=icon, on_click=on_click).props(f'flat round dense aria-label="{tooltip}"')
        button.tooltip(tooltip)
        return button

    def _build_panel(self) -> None:
        with ui.element('div').classes('lc-panel'):
            with ui.element('div').classes('lc-card'):
                with ui.row().classes('lc-card-head'):
                    section_title('Presets')
                    self.preset_badge = ui.label().classes('lc-badge')
                with ui.element('div').classes('lc-presets'):
                    for number, name in enumerate(PRESETS, start=1):
                        button = ui.button(name, on_click=lambda n=name: self.apply_preset(n))
                        button.props('flat no-caps').classes(f'lc-preset lc-preset-{number}')
                        button.tooltip(f'Shortcut: {number}')
                        self.preset_buttons[name] = button

            with ui.element('div').classes('lc-card'):
                section_title('Stroke')
                for spec in SLIDERS:
                    self._build_slider(spec)

            self._build_faults()

            with ui.element('div').classes('lc-card'):
                section_title('Muscle emphasis')
                emphasis = ui.toggle(
                    EMPHASIS_LABELS, value=self.view.emphasis, on_change=lambda e: self.update(emphasis=e.value)
                )
                emphasis.props('no-caps spread unelevated').classes('lc-segmented')

            with ui.element('div').classes('lc-card'):
                section_title('Estimates')
                with ui.element('div').classes('lc-stats'):
                    for key, caption in STATS:
                        with ui.element('div').classes('lc-stat'):
                            self.stats[key] = ui.label().classes('lc-stat-value')
                            ui.label(caption).classes('lc-stat-caption')
                with ui.element('div').classes('lc-hold') as self.hold_banner:
                    self.hold_icon = ui.icon('check_circle')
                    self.hold_text = ui.label()

            ui.label(
                'Coaching estimates only — not measured, EMG, or medical data. '
                'Drag to orbit · scroll to zoom · Space play · ←/→ step · 1–4 presets · C camera.'
            ).classes('lc-footnote')

    def _build_faults(self) -> None:
        with ui.element('div').classes('lc-card'):
            with ui.row().classes('lc-card-head'):
                section_title('Stroke faults')
                with ui.row().classes('items-center gap-1'):
                    self.fault_badge = ui.label().classes('lc-badge')
                    self.clear_faults = ui.button('Clear', on_click=lambda: self.update(faults=frozenset()), color=None)
                    self.clear_faults.props('flat dense no-caps').classes('lc-clear')
            with ui.element('div').classes('lc-faults'):
                for key, fault in FAULTS.items():
                    button = ui.button(
                        fault.label, icon=FAULT_ICONS[key], on_click=lambda k=key: self.toggle_fault(k), color=None
                    )
                    button.props(f'flat no-caps aria-pressed=false aria-label="{fault.label}"')
                    button.classes(f'lc-fault lc-fault-{key}').tooltip(fault.hint)
                    self.fault_buttons[key] = button
            self.cues = ui.element('div').classes('lc-cues')

    def _build_slider(self, spec: SliderSpec) -> None:
        lo, hi = SETTING_RANGES[spec.key]
        value = getattr(self.view.settings, spec.key)
        with ui.element('div').classes('lc-control'):
            with ui.row().classes('lc-control-head'):
                ui.label(spec.label).classes('lc-control-label')
                ui.icon('info_outline').classes('lc-info').tooltip(spec.hint)
                ui.element('div').classes('lc-spacer')
                self.slider_values[spec.key] = ui.label(f'{value}{spec.unit}').classes('lc-value')
            self.sliders[spec.key] = ui.slider(
                min=lo,
                max=hi,
                step=1,
                value=value,
                on_change=lambda e, s=spec: self.on_slider(s, e.value),
            ).props(f'aria-label="{spec.label}"')
            if spec.low:
                with ui.row().classes('lc-control-range'):
                    ui.label(spec.low)
                    ui.label(spec.high)

    # ---- state ---------------------------------------------------------------------------------

    def update(self, **changes: Any) -> None:
        new = replace(self.view, **changes)
        if new != self.view:
            self.view = new
            self._render()

    def on_slider(self, spec: SliderSpec, value: float) -> None:
        self.slider_values[spec.key].text = f'{value:.0f}{spec.unit}'
        if not self._applying_preset:
            self.update(settings=self.view.settings.with_values(**{spec.key: int(value)}))

    def apply_preset(self, name: str) -> None:
        preset = PRESETS[name]
        self._applying_preset = True
        try:
            for key, slider in self.sliders.items():
                slider.value = getattr(preset, key)
        finally:
            self._applying_preset = False
        self.update(settings=preset)

    def toggle_play(self) -> None:
        self.update(playing=not self.view.playing)

    def toggle_fault(self, key: str) -> None:
        self.update(faults=self.view.with_fault(key, key not in self.view.faults).faults)

    def step(self, amount: float) -> None:
        self.update(playing=False)
        self.engine.step(amount)

    async def start(self) -> None:
        await ui.context.client.connected()
        self.engine.start(self.scene.id, self.scene_ids, self.view.render_params())

    # ---- rendering -----------------------------------------------------------------------------

    def _render(self) -> None:
        metrics = self.view.metrics()
        self._render_transport()
        self._render_presets()
        self._render_faults()
        self._render_stats(metrics)
        self._render_timeline()
        self.engine.set(self.view.render_params(metrics))

    def _render_transport(self) -> None:
        playing = self.view.playing
        self.play_button.props(f'icon={"pause" if playing else "play_arrow"}')
        self.play_button.props(f'aria-label="{"Pause" if playing else "Play"}"')

    def _render_presets(self) -> None:
        active = matching_preset(self.view.settings)
        self.preset_badge.text = 'Custom' if active is None else 'Preset'
        self.preset_badge.classes(replace='lc-badge lc-badge-custom' if active is None else 'lc-badge')
        for name, button in self.preset_buttons.items():
            if name == active:
                button.classes(add='lc-active')
            else:
                button.classes(remove='lc-active')

    def _render_faults(self) -> None:
        active = self.view.faults
        if active == self._fault_layout:
            return
        self._fault_layout = active
        count = len(active)
        self.fault_badge.text = f'{count} on' if count else 'Clean'
        self.fault_badge.classes(replace='lc-badge lc-badge-fault' if count else 'lc-badge')
        self.clear_faults.set_visibility(bool(count))
        for key, button in self.fault_buttons.items():
            on = key in active
            if on:
                button.classes(add='lc-active')
            else:
                button.classes(remove='lc-active')
            button.props(f'aria-pressed={str(on).lower()}')
        self.cues.clear()
        with self.cues:
            if not active:
                ui.label('Switch on a fault to see how it changes the stroke and the estimates.').classes(
                    'lc-cue lc-cue-empty'
                )
            for key, fault in FAULTS.items():
                if key in active:
                    with ui.element('div').classes('lc-cue'):
                        ui.label(f'{fault.label}: ').classes('lc-cue-name')
                        ui.label(fault.cue).classes('inline')

    def _render_stats(self, metrics: Metrics) -> None:
        tone = 'lc-good' if metrics.holding else 'lc-bad'
        self.stats['rate'].text = f'{self.view.settings.rate} spm'
        self.stats['dps'].text = f'{metrics.distance_per_stroke:.2f} m'
        self.stats['spl'].text = f'{metrics.strokes_per_25:.1f}'
        self.stats['t25'].text = format_duration(metrics.seconds_per_25)
        self.stats['dps'].classes(replace=f'lc-stat-value {tone}')
        self.hold_banner.classes(replace=f'lc-hold {tone}')
        self.hold_icon.name = 'check_circle' if metrics.holding else 'warning'
        self.hold_text.text = 'Hand holding water' if metrics.holding else 'Hand slipping — catch is losing grip'

    def _render_timeline(self) -> None:
        """Size the phase segments; recovery moves with stroke rate and spinning arms squeeze the pull."""
        length = path_length(self.view.settings.rate)
        starts = (0.0, *timeline_boundaries(length, 'rushing' in self.view.faults), 1.0)
        if starts == self._segment_layout:
            return
        self._segment_layout = starts
        for segment, (start, end) in zip(self.segments, pairwise(starts), strict=True):
            segment.style(f'left:{start * 100:.2f}%; width:{(end - start) * 100:.2f}%')


@ui.page('/')
async def index() -> None:
    page = LongCatchPage()
    page.build()
    await page.start()
