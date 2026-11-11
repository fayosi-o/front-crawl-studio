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
    TRAIL_SECONDS,
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

STEP = 0.05  # fraction of a cycle moved by each step button or arrow key


@dataclass(frozen=True, slots=True)
class SliderSpec:
    """Label, unit, tooltip, and optional end-of-range captions for one stroke slider."""

    key: str  # StrokeSettings field name
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
        'depth',
        'Stroke depth',
        '%',
        'How deep the hand travels under the body during the pull.',
        'close to body',
        'deep',
    ),
    SliderSpec(
        'entry',
        'Entry angle',
        '°',
        'How steeply the arm extends after the hand enters.',
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
        'Flutter-kick size.',
        'still legs',
        'strong flutter',
    ),
)
# Import-time checks that the UI tables stay in step with the model.
assert {spec.key for spec in SLIDERS} == set(SETTING_RANGES)

EMPHASIS_LABELS = {'back': 'Back', 'triceps': 'Triceps', 'core': 'Hips/core', 'balanced': 'Balanced'}
ANGLE_LABELS = {'top': 'Top', 'side': 'Side', 'front': 'Front', 'below': 'Below'}
TRAIL_LABELS = {'off': 'Off', 'hands': 'Hands', 'feet': 'Feet', 'both': 'Both'}
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
    """Small uppercase heading used at the top of each panel card."""
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
        self.second_view: ui.scene_view | None = None
        # Last-rendered layouts; renderers skip DOM work when nothing changed.
        self._view_layout: tuple | None = None

    # ---- layout -------------------------------------------------------------------------------

    def build(self) -> None:
        """Create the whole page: inline styles and engine, 3D stage, and side panel."""
        ui.add_head_html(stylesheet())
        ui.add_body_html(engine_script())
        ui.colors(primary=PALETTE.hold)
        with ui.element('div').classes('lc-root'):
            self._build_stage()
            self._build_panel()
        self._render()

    def _build_stage(self) -> None:
        """3D scene (plus a hidden second pane for split view) and the HUD overlays."""
        with ui.element('div').classes('lc-stage'):
            with ui.element('div').classes('lc-views') as self.views:
                with ui.element('div').classes('lc-view'):
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
                    ui.label('Orbit view').classes('lc-view-label')
                with ui.element('div').classes('lc-view lc-view-second') as self.second_pane:
                    self.angle_label = ui.label().classes('lc-view-label')

            with ui.element('div').classes('lc-hud-top'):
                with ui.element('div').classes('lc-glass lc-brand'):
                    ui.label('Long Catch').classes('lc-title')
                    ui.label('Front-crawl stroke explorer').classes('lc-subtitle')
                    with ui.row().classes('lc-legend'):
                        for css, text in (('hold', 'holding'), ('slip', 'slipping'), ('patch', 'emphasis')):
                            with ui.element('span').classes('lc-legend-item'):
                                ui.element('span').classes(f'lc-dot lc-dot-{css}')
                                ui.label(text)
                with ui.element('div').classes('lc-glass lc-arms'):
                    for side in ('right', 'left'):
                        with ui.element('div').classes('lc-arm'):
                            ui.label(f'{side.title()} arm').classes('lc-arm-side')
                            # The engine rewrites this text every frame.
                            ui.label(Phase.ENTRY.label).classes(f'lc-arm-phase lc-arm-{side}')
            self._build_transport()

    def _build_transport(self) -> None:
        """Bottom dock: phase timeline, step and play buttons, speed, and camera reset.

        The engine finds these elements by their ``lc-*`` classes to drive the
        timeline marker and cycle percentage, and to wire up shortcuts.
        """
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
                reset = self._icon_button('center_focus_strong', 'Reset camera (C)', self.engine.reset_camera)
                reset.classes('lc-reset-camera')

    @staticmethod
    def _icon_button(icon: str, tooltip: str, on_click) -> ui.button:
        """Round icon-only button; the tooltip doubles as its accessible name."""
        button = ui.button(icon=icon, on_click=on_click).props(f'flat round dense aria-label="{tooltip}"')
        button.tooltip(tooltip)
        return button

    def _build_panel(self) -> None:
        """Right-hand settings panel, one card per group of controls."""
        with ui.element('div').classes('lc-panel'):
            with ui.element('div').classes('lc-card'):
                with ui.row().classes('lc-card-head'):
                    section_title('Presets')
                    self.preset_badge = ui.label().classes('lc-badge')
                with ui.element('div').classes('lc-presets'):
                    for number, name in enumerate(PRESETS, start=1):
                        button = ui.button(name, on_click=lambda n=name: self.apply_preset(n), color=None)
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

            self._build_view()

            with ui.element('div').classes('lc-card'):
                section_title('Stroke metrics')
                with ui.element('div').classes('lc-stats'):
                    for key, caption in STATS:
                        with ui.element('div').classes('lc-stat'):
                            self.stats[key] = ui.label().classes('lc-stat-value')
                            ui.label(caption).classes('lc-stat-caption')
                with ui.element('div').classes('lc-hold') as self.hold_banner:
                    self.hold_icon = ui.icon('check_circle')
                    self.hold_text = ui.label()

    def _build_view(self) -> None:
        """View card: split-view switch, second camera angle, and ghost-trail controls."""
        with ui.element('div').classes('lc-card'):
            with ui.row().classes('lc-card-head'):
                section_title('View')
                split = ui.switch('Split view', on_change=lambda e: self.update(split=e.value))
                split.classes('lc-split-toggle').tooltip('Shortcut: V')
            self.angle_toggle = ui.toggle(
                ANGLE_LABELS, value=self.view.angle, on_change=lambda e: self.update(angle=e.value)
            )
            self.angle_toggle.props('no-caps spread unelevated').classes('lc-segmented').tooltip('Second camera angle')
            with ui.element('div').classes('lc-control'):
                with ui.row().classes('lc-control-head'):
                    ui.label('Ghost trail').classes('lc-control-label')
                    ui.icon('info_outline').classes('lc-info').tooltip(
                        'A fading smoke trail behind the fingertips and toes that drifts back with the water.'
                    )
                trail = ui.toggle(TRAIL_LABELS, value=self.view.trail, on_change=lambda e: self.update(trail=e.value))
                trail.props('no-caps spread unelevated').classes('lc-segmented')
            with ui.element('div').classes('lc-control'):
                with ui.row().classes('lc-control-head'):
                    ui.label('Trail length').classes('lc-control-label')
                    ui.element('div').classes('lc-spacer')
                    self.trail_value = ui.label().classes('lc-value')
                lo, hi = TRAIL_SECONDS
                self.trail_slider = ui.slider(
                    min=lo,
                    max=hi,
                    step=0.5,
                    value=self.view.trail_seconds,
                    on_change=lambda e: self.update(trail_seconds=float(e.value)),
                ).props('aria-label="Trail length"')
                with ui.row().classes('lc-control-range'):
                    ui.label('short wisp')
                    ui.label('long trail')

    def _build_faults(self) -> None:
        """Fault chips that toggle on click, a Clear button, and a list of coaching cues."""
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
        """One labelled stroke slider with a live value pill and optional range captions."""
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
        """Replace the view state (which validates it) and re-render if anything changed."""
        new = replace(self.view, **changes)
        if new != self.view:
            self.view = new
            self._render()

    def on_slider(self, spec: SliderSpec, value: float) -> None:
        """Update the value pill; apply the change unless a preset is moving the sliders."""
        self.slider_values[spec.key].text = f'{value:.0f}{spec.unit}'
        if not self._applying_preset:
            self.update(settings=self.view.settings.with_values(**{spec.key: int(value)}))

    def apply_preset(self, name: str) -> None:
        """Move every slider to the preset, then apply it as a single state change."""
        preset = PRESETS[name]
        # Suppress per-slider updates so the preset applies as one render.
        self._applying_preset = True
        try:
            for key, slider in self.sliders.items():
                slider.value = getattr(preset, key)
        finally:
            self._applying_preset = False
        self.update(settings=preset)

    def toggle_play(self) -> None:
        """Play or pause the animation."""
        self.update(playing=not self.view.playing)

    def toggle_fault(self, key: str) -> None:
        """Switch one stroke fault on or off."""
        self.update(faults=self.view.with_fault(key, key not in self.view.faults).faults)

    def step(self, amount: float) -> None:
        """Pause, then nudge the cycle phase by ``amount``."""
        self.update(playing=False)
        self.engine.step(amount)

    async def start(self) -> None:
        """Wait for the browser to connect, then hand the scene to the engine."""
        await ui.context.client.connected()
        self.engine.start(self.scene.id, self.scene_ids, self.view.render_params())

    # ---- rendering -----------------------------------------------------------------------------

    def _render(self) -> None:
        """Sync every widget and the engine with the current view state."""
        metrics = self.view.metrics()
        self._render_transport()
        self._render_presets()
        self._render_faults()
        self._render_stats(metrics)
        self._render_timeline()
        self._render_view()
        self.engine.set(self.view.render_params(metrics))

    def _render_view(self) -> None:
        """Show or hide the second camera; it is created on first use so a single view stays cheap."""
        v = self.view
        self.trail_value.text = f'{v.trail_seconds:.1f} s'
        self._enable(self.trail_slider, v.trail != 'off')
        layout = (v.split, v.angle)
        if layout == self._view_layout:
            return
        split_changed = self._view_layout is None or self._view_layout[0] != v.split
        self._view_layout = layout
        if v.split and self.second_view is None:
            with self.second_pane:
                self.second_view = ui.scene_view(self.scene, camera=ui.scene.perspective_camera(fov=42), fps=60)
        if v.split:
            self.views.classes(add='lc-split')
        else:
            self.views.classes(remove='lc-split')
        self._enable(self.angle_toggle, v.split)
        self.angle_label.text = f'{ANGLE_LABELS[v.angle]} view'
        if self.second_view is not None:
            self.engine.set_view(self.second_view.id, v.angle)
        if split_changed:
            self.engine.fit()

    @staticmethod
    def _enable(element: ui.element, enabled: bool) -> None:
        """Toggle Quasar's ``disable`` prop."""
        if enabled:
            element.props(remove='disable')
        else:
            element.props('disable')

    def _render_transport(self) -> None:
        """Swap the play button's icon and accessible label."""
        playing = self.view.playing
        self.play_button.props(f'icon={"pause" if playing else "play_arrow"}')
        self.play_button.props(f'aria-label="{"Pause" if playing else "Play"}"')

    def _render_presets(self) -> None:
        """Highlight the preset that matches the settings, or badge the stroke as Custom."""
        active = matching_preset(self.view.settings)
        self.preset_badge.text = 'Custom' if active is None else 'Preset'
        self.preset_badge.classes(replace='lc-badge lc-badge-custom' if active is None else 'lc-badge')
        for name, button in self.preset_buttons.items():
            if name == active:
                button.classes(add='lc-active')
            else:
                button.classes(remove='lc-active')

    def _render_faults(self) -> None:
        """Update fault chips, the count badge, and the cue list (only when faults change)."""
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
                hint = 'Switch on a fault to see how it changes the stroke.'
                ui.label(hint).classes('lc-cue lc-cue-empty')
            for key, fault in FAULTS.items():
                if key in active:
                    with ui.element('div').classes('lc-cue'):
                        ui.label(f'{fault.label}: ').classes('lc-cue-name')
                        ui.label(fault.cue).classes('inline')

    def _render_stats(self, metrics: Metrics) -> None:
        """Fill in the estimate tiles and colour the hold banner."""
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
    """Build a fresh page, with its own state, for each browser tab."""
    page = LongCatchPage()
    page.build()
    await page.start()
