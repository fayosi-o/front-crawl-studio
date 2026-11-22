"""NiceGUI page: stage overlays, transport controls, and the settings panel."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Any

from nicegui import ui

from long_catch.auth import hosted
from long_catch.engine import BrowserEngine, RaceEngine, engine_script
from long_catch.model import (
    DRILLS,
    EMPHASES,
    FAULTS,
    PHASE_LABELS,
    PLAYBACK_SPEEDS,
    PRESETS,
    RACE_DISTANCES,
    RACE_PLAYBACK_SPEEDS,
    SETTING_RANGES,
    TRAIL_SECONDS,
    Advice,
    Metrics,
    Phase,
    RaceConfig,
    StrokeSettings,
    ViewState,
    advice,
    felt_load,
    format_duration,
    hand_area,
    matching_preset,
    path_length,
    preset_for,
    timeline_boundaries,
)
from long_catch.swimmer import SwimmerBuilder
from long_catch.theme import PALETTE, stylesheet

STEP = 0.05  # fraction of a cycle moved by each step button or arrow key
TRAIL_STEP = 0.5  # seconds per notch of the trail-length slider
NARROW_SEGMENT = 0.05  # timeline segments shorter than this share of the cycle hide their label


@dataclass(frozen=True, slots=True)
class SliderSpec:
    """Label, unit, tooltip, and optional end-of-range captions for one stroke slider."""

    key: str  # StrokeSettings field name
    label: str
    unit: str
    hint: str
    low: str = ''
    high: str = ''
    step: int = 1


SLIDERS: tuple[SliderSpec, ...] = (
    SliderSpec(
        'rate',
        'Stroke rate',
        ' spm',
        'Hand entries per minute. Lower rates lengthen the underwater path but coast longer between strokes; '
        'higher rates go faster for more effort, and above about 50 spm a weak catch starts to slip.',
    ),
    SliderSpec('catch', 'Catch quality', '%', 'How early and firmly the forearm sets against the water.'),
    SliderSpec(
        'roll',
        'Body roll',
        '°',
        'Peak rotation of the chest about the long axis. About 35–55° costs nothing; flatter or further adds drag.',
    ),
    SliderSpec(
        'glide',
        'Glide length',
        '%',
        'Time spent reaching forward before the catch, not distance in metres. '
        '50% is normal. Longer glides lose more momentum; stroke rate stays unchanged.',
        'earlier catch',
        'longer glide',
    ),
    SliderSpec('slip', 'Slip', '%', 'How much the hand slides through the water instead of holding it.'),
    SliderSpec(
        'width',
        'Pull width',
        '%',
        'Where the hand travels under water: in under the body with the elbow out (power diamond), '
        'or wide of the shoulder with a straighter arm. A hand wide of the shoulder sweeps sideways and holds less.',
        'under body',
        'wide of shoulder',
    ),
    SliderSpec(
        'depth',
        'Stroke depth',
        '%',
        'How deep the hand travels under the body during the pull. A deep, straight arm presses down '
        'before it pushes back; a hand held tight to the body has a short lever.',
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
        'Kick size. A kick lifts the legs; still legs sink and drag. A six-beat kick adds a little speed '
        'for a lot of effort, and a big kick leaves the streamline.',
        'still legs',
        'strong flutter',
    ),
    SliderSpec(
        'beats',
        'Kick timing',
        '-beat',
        'Kicks per arm cycle. In a two-beat kick each downbeat lands as the opposite hand catches '
        'and snaps the hips onto the next side.',
        '2-beat glide',
        '6-beat drive',
        step=2,
    ),
    SliderSpec(
        'breath',
        'Breathing',
        ' strokes',
        'Hand entries per breath. Odd counts alternate sides (bilateral breathing); '
        'even counts always breathe to the right. With a head lift, every breath costs time.',
        'every 2',
        'every 5',
    ),
    SliderSpec(
        'height',
        'Swimmer height',
        ' cm',
        'Standing height. Longer levers cover more distance per stroke for the same effort. Presets keep it.',
        'shorter',
        'taller',
    ),
)
# Import-time checks that the UI tables stay in step with the model.
assert {spec.key for spec in SLIDERS} == set(SETTING_RANGES)
SLIDER_SPECS = {spec.key: spec for spec in SLIDERS}
MAIN_SLIDERS = ('rate', 'catch', 'slip', 'drive')

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
    'headlift': 'arrow_upward',
    'earlyexit': 'exit_to_app',
    'droppedelbow': 'vertical_align_bottom',
    'lopsided': 'balance',
    'earlyroll': 'sync',
    'wristpress': 'back_hand',
    'shoulderreach': 'open_in_full',
    'hipfinish': 'rotate_right',
    'pushdown': 'south',
    'flatpush': 'arrow_back',
    'upsweep': 'north_east',
    'paddles': 'pan_tool',
}
assert set(FAULT_ICONS) == set(FAULTS)

DRILL_LABELS = {'off': 'Full', 'catchup': 'Catch-up', 'single': 'One arm', 'fist': 'Fist'}
assert set(DRILL_LABELS) == set(DRILLS)
BRAND = 'Front-crawl stroke explorer'

PACE: tuple[tuple[str, str, str], ...] = (
    ('pace', 'Pace / 100 m', 'Steady-speed time for 100 m, without dives or turns.'),
    ('swolf', 'SWOLF', 'Strokes plus seconds for one 25 m length. Lower is more efficient.'),
    ('speed', 'Speed', 'Average swimming speed.'),
    (
        'effort',
        'Effort',
        'Estimated work rate against an all-out sprint: the push at this pace, hand slip, arm turnover and the kick.',
    ),
)

STATS: tuple[tuple[str, str, str], ...] = (
    ('dps', 'Distance / stroke', 'm/stroke'),
    ('spl', 'Strokes / 25 m', 'Stk/25'),
    ('t25', 'Time / 25 m', 'Time/25'),
    ('carry', 'Momentum carry', 'Carry'),
)


def bounded_number(value: Any, low: float, high: float, step: float = 1) -> float | None:
    """A browser value clamped to [low, high] and snapped to the control's ``step``, or None if it is
    not a finite number. A client can send anything over the socket, not only what the control allows.
    Whole-number bounds and step give an int."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return low + step * round((min(high, max(low, number)) - low) / step)


def section_title(text: str) -> ui.label:
    """Small uppercase heading used at the top of each panel card."""
    return ui.label(text).classes('lc-section-title')


def stroke_slider(
    spec: SliderSpec, value: int, on_change: Callable[[Any], None], prefix: str = ''
) -> tuple[ui.slider, ui.label]:
    """Shared stroke control for the studio and the selected race swimmer."""
    lo, hi = SETTING_RANGES[spec.key]
    with ui.element('div').classes('lc-control'):
        with ui.row().classes('lc-control-head'):
            ui.label(spec.label).classes('lc-control-label')
            ui.icon('info_outline').classes('lc-info').tooltip(spec.hint)
            ui.element('div').classes('lc-spacer')
            value_label = ui.label(f'{value}{spec.unit}').classes('lc-value')
        slider = ui.slider(min=lo, max=hi, step=spec.step, value=value, on_change=lambda e: on_change(e.value)).props(
            f'aria-label="{prefix}{spec.label}"'
        )
        if spec.low:
            with ui.row().classes('lc-control-range'):
                ui.label(spec.low)
                ui.label(spec.high)
    return slider, value_label


def stroke_controls(
    settings: StrokeSettings, on_change: Callable[[SliderSpec, Any], None], prefix: str = ''
) -> tuple[dict[str, ui.slider], dict[str, ui.label]]:
    """Keep the main pace controls visible and group detailed stroke settings."""
    sliders, values = {}, {}

    def build(spec: SliderSpec) -> None:
        sliders[spec.key], values[spec.key] = stroke_slider(
            spec, getattr(settings, spec.key), lambda value: on_change(spec, value), prefix
        )

    for spec in SLIDERS:
        if spec.key in MAIN_SLIDERS:
            build(spec)
    with ui.expansion('Motion details', caption='Glide, roll, width, depth, entry, kick, breathing and height').classes(
        'lc-motion-details w-full'
    ):
        for spec in SLIDERS:
            if spec.key not in MAIN_SLIDERS:
                build(spec)
    return sliders, values


def change_text(settings: StrokeSettings, changes: tuple[tuple[str, int], ...]) -> str:
    """Describe setting changes as 'Slip 8% → 0%'."""
    parts = []
    for key, value in changes:
        spec = SLIDER_SPECS[key]
        parts.append(f'{spec.label} {getattr(settings, key)}{spec.unit} → {value}{spec.unit}')
    return ', '.join(parts)


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
        self.pace: dict[str, ui.label] = {}
        self._advice_layout: tuple[tuple[Advice, ...], StrokeSettings] | None = None
        self.segments: list[ui.element] = []
        self._applying_preset = False
        self._segment_layout: tuple[float, ...] = ()
        self.second_view: ui.scene_view | None = None
        # Last-rendered layouts; renderers skip DOM work when nothing changed.
        self._view_layout: tuple | None = None
        self.pinned = False
        self.dock_shown = True
        self.race: RaceMode | None = None

    # ---- layout -------------------------------------------------------------------------------

    def build(self) -> None:
        """Create the whole page: inline styles and engine, 3D stage, and side panel."""
        ui.add_head_html(stylesheet())
        ui.add_body_html(engine_script())
        ui.colors(primary=PALETTE.hold)
        with ui.element('header').classes('lc-header'):
            with ui.tabs(value='studio', on_change=lambda e: self.switch_mode(e.value)).classes('lc-mode-tabs'):
                ui.tab('studio', label='Stroke studio', icon='accessibility_new').props('aria-label="Stroke studio"')
                ui.tab('race', label='Race', icon='sports_score').props('aria-label="Race"')
            with ui.element('section').classes('lc-estimates').props('aria-label="Stroke estimates"'):
                with ui.element('div').classes('lc-estimate-context'):
                    self.estimate_title = ui.label().classes('lc-section-title')
                    with ui.element('div').classes('lc-hold') as self.hold_banner:
                        self.hold_icon = ui.icon('check_circle')
                        self.hold_text = ui.label()
                with ui.element('div').classes('lc-stats'):
                    for key, caption, short in STATS:
                        with ui.element('div').classes('lc-stat').props(f'title="{caption}"'):
                            self.stats[key] = ui.label().classes('lc-stat-value')
                            with ui.element('div').classes('lc-stat-caption'):
                                ui.label(caption).classes('lc-caption-full')
                                ui.label(short).classes('lc-caption-short').props('aria-hidden=true')
        with ui.element('div').classes('lc-root lc-studio') as self.studio:
            self._build_stage()
            self._build_panel()
        self.race_space = ui.element('div').classes('lc-root lc-race')
        self.race_space.set_visibility(False)
        self._render()

    def switch_mode(self, mode: str) -> None:
        """Retain the studio intact; build the two race scenes only on first use."""
        racing = mode == 'race'
        self.studio.set_visibility(not racing)
        self.race_space.set_visibility(racing)
        self.scene.props(f'fps={1 if racing else 60}')
        if self.second_view is not None:
            self.second_view.props(f'fps={60 if not racing and self.view.split else 1}')
        self.engine.set_active(not racing)
        if racing and self.race is None:
            with self.race_space:
                self.race = RaceMode(lambda: self.view, self._render_stats)
                self.race.build()
            self.race.start()
        elif self.race is not None:
            self.race.set_active(racing)
            if racing:
                self.race._render_editor()
        if not racing:
            self._render_stats(self.view.metrics())

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
                    self.brand = ui.label(BRAND).classes('lc-subtitle')
                    with ui.row().classes('lc-legend'):
                        for css, text in (('hold', 'holding'), ('slip', 'slipping'), ('patch', 'emphasis')):
                            with ui.element('span').classes('lc-legend-item'):
                                ui.element('span').classes(f'lc-dot lc-dot-{css}')
                                ui.label(text)
                with ui.element('div').classes('lc-glass lc-arms'):
                    for side in ('right', 'left'):
                        with ui.element('div').classes('lc-arm'):
                            ui.label(f'{side.title()} arm').classes('lc-arm-side')
                            # The engine rewrites this text and the load bar every frame.
                            ui.label(Phase.ENTRY.label).classes(f'lc-arm-phase lc-arm-{side}')
                            with ui.element('div').classes(f'lc-load lc-load-{side}').props('aria-hidden=true'):
                                ui.label('Load').classes('lc-load-label')
                                with ui.element('div').classes('lc-load-track'):
                                    ui.element('div').classes('lc-load-fill')
            ui.label('Drag to orbit / scroll to zoom').classes('lc-camera-hint')
            self._build_transport()
            self.dock_button = self._icon_button('expand_more', 'Hide / show controls (H)', self.toggle_dock)
            self.dock_button.classes('lc-glass lc-dock-toggle').props('aria-pressed=true')

    def _build_transport(self) -> None:
        """Bottom dock: phase timeline, step and play buttons, speed, and camera reset.

        The engine finds these elements by their ``lc-*`` classes to drive the
        timeline marker and cycle percentage, and to wire up shortcuts.
        """
        with ui.element('div').classes('lc-glass lc-dock'):
            with (
                ui.element('div')
                .classes('lc-timeline')
                .props(
                    'role=slider tabindex=0 aria-label="Right-arm cycle" aria-valuemin=0 aria-valuemax=100 '
                    'aria-valuenow=0 title="Drag to inspect; arrow keys step, Home/End seek"'
                )
            ):
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
                self.pin_button = self._icon_button('push_pin', 'Pin swimmer while scrolling (P)', self.toggle_pin)
                self.pin_button.classes('lc-pin-toggle').props('aria-pressed=false')
                reset = self._icon_button('center_focus_strong', 'Reset camera (C)', self.engine.reset_camera)
                reset.classes('lc-reset-camera')

    def toggle_dock(self) -> None:
        """Hide the playback dock for an unobstructed view; shortcuts keep working."""
        self.dock_shown = not self.dock_shown
        if self.dock_shown:
            self.studio.classes(remove='lc-dock-hidden')
        else:
            self.studio.classes(add='lc-dock-hidden')
        icon = 'expand_more' if self.dock_shown else 'expand_less'
        self.dock_button.props(f'icon={icon} aria-pressed={str(self.dock_shown).lower()}')

    def toggle_pin(self) -> None:
        """Keep the swimmer on screen while the settings scroll beneath it (stacked layout)."""
        self.pinned = not self.pinned
        if self.pinned:
            self.studio.classes(add='lc-pinned')
            self.pin_button.classes(add='lc-active')
        else:
            self.studio.classes(remove='lc-pinned')
            self.pin_button.classes(remove='lc-active')
        self.pin_button.props(f'aria-pressed={str(self.pinned).lower()}')
        self.engine.fit()

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
                self.sliders, self.slider_values = stroke_controls(self.view.settings, self.on_slider)

            self._build_faults()
            self._build_coach()
            self._build_drills()

            with ui.element('div').classes('lc-card'):
                section_title('Muscle emphasis')
                emphasis = ui.toggle(
                    EMPHASIS_LABELS, value=self.view.emphasis, on_change=lambda e: self.update(emphasis=e.value)
                )
                emphasis.props('no-caps spread unelevated').classes('lc-segmented')

            self._build_view()

    def _build_view(self) -> None:
        """View card: split-view switch, second camera angle, and ghost-trail controls."""
        with ui.element('div').classes('lc-card'):
            with ui.row().classes('lc-card-head'):
                section_title('View')
                split = ui.switch('Split view', on_change=lambda e: self.set_switch('split', e.value))
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
                    step=TRAIL_STEP,
                    value=self.view.trail_seconds,
                    on_change=lambda e: self.set_trail_seconds(e.value),
                ).props('aria-label="Trail length"')
                with ui.row().classes('lc-control-range'):
                    ui.label('short wisp')
                    ui.label('long trail')
            pressure = ui.switch(
                'Water pressure', value=self.view.pressure, on_change=lambda e: self.set_switch('pressure', e.value)
            )
            pressure.classes('lc-pressure-toggle').tooltip(
                'Simulated pressure: clouds build where the palm, forearm and feet load the water, '
                'are pushed backward, and dissipate. Slipping hands build little.'
            )

    def _build_faults(self) -> None:
        """Fault chips that toggle on click, a Clear button, and a list of coaching cues."""
        with ui.element('div').classes('lc-card'):
            with ui.row().classes('lc-card-head'):
                section_title('Stroke faults & form')
                with ui.row().classes('items-center gap-1'):
                    self.fault_badge = ui.label().classes('lc-badge')
                    self.clear_faults = ui.button('Clear', on_click=lambda: self.update(faults=frozenset()), color=None)
                    self.clear_faults.props('flat dense no-caps').classes('lc-clear')
            for kind, title in (('fault', None), ('form', 'Good form'), ('kit', 'Equipment')):
                if title:
                    ui.label(title).classes('lc-form-title')
                with ui.element('div').classes('lc-faults'):
                    self._build_fault_buttons(kind)
            self.cues = ui.element('div').classes('lc-cues')

    def _build_fault_buttons(self, kind: str) -> None:
        """The chips for the faults, the good-form cues that fix them, or the training equipment."""
        for key, fault in FAULTS.items():
            if kind != ('kit' if fault.kit else 'form' if fault.good else 'fault'):
                continue
            button = ui.button(
                fault.label, icon=FAULT_ICONS[key], on_click=lambda k=key: self.toggle_fault(k), color=None
            )
            button.props(f'flat no-caps aria-pressed=false aria-label="{fault.label}"')
            button.classes(f'lc-fault lc-fault-{key}').tooltip(fault.hint)
            self.fault_buttons[key] = button

    def _build_coach(self) -> None:
        """Pace summary and the ranked changes that would save the most time at this rate."""
        with ui.element('div').classes('lc-card lc-coach').props('aria-label="Fix first"'):
            with ui.row().classes('lc-card-head'):
                section_title('Fix first')
                ui.label('same rate').classes('lc-badge').tooltip(
                    'Suggestions keep the stroke rate; rate is a pacing choice, so only technique is ranked.'
                )
            with ui.element('div').classes('lc-pace'):
                for key, caption, hint in PACE:
                    with ui.element('div').classes('lc-pace-item').props(f'title="{hint}"'):
                        self.pace[key] = ui.label().classes('lc-pace-value')
                        ui.label(caption).classes('lc-stat-caption')
            self.advice_list = ui.element('div').classes('lc-advice').props('aria-live=polite')

    def _build_drills(self) -> None:
        """Drill picker: the swimmer demonstrates a practice pattern; estimates stay on the full stroke."""
        with ui.element('div').classes('lc-card'):
            section_title('Drills')
            drill = ui.toggle(DRILL_LABELS, value=self.view.drill, on_change=lambda e: self.update(drill=e.value))
            drill.props('no-caps spread unelevated').classes('lc-segmented lc-drill-toggle')
            self.drill_hint = ui.label().classes('lc-drill-hint')

    # ---- state ---------------------------------------------------------------------------------

    def update(self, **changes: Any) -> None:
        """Replace the view state (which validates it) and re-render if anything changed."""
        new = replace(self.view, **changes)
        if new != self.view:
            self.view = new
            self._render()

    def on_slider(self, spec: SliderSpec, raw: Any) -> None:
        """Update the value pill; apply the change unless a preset is moving the sliders."""
        value = bounded_number(raw, *SETTING_RANGES[spec.key], spec.step)
        if value is None:
            return
        self.slider_values[spec.key].text = f'{value}{spec.unit}'
        if not self._applying_preset:
            self.update(settings=self.view.settings.with_values(**{spec.key: value}))

    def set_trail_seconds(self, raw: Any) -> None:
        """Ghost-trail length from its slider, kept on the slider's range and notches."""
        seconds = bounded_number(raw, *TRAIL_SECONDS, TRAIL_STEP)
        if seconds is not None:
            self.update(trail_seconds=seconds)

    def set_switch(self, name: str, value: Any) -> None:
        """A view switch (split view, water pressure); only true or false from the browser count."""
        if isinstance(value, bool):
            self.update(**{name: value})

    def _move_sliders(self, settings: StrokeSettings) -> None:
        """Move every slider to ``settings`` without triggering one update per slider."""
        self._applying_preset = True
        try:
            for key, slider in self.sliders.items():
                slider.value = getattr(settings, key)
        finally:
            self._applying_preset = False

    def apply_preset(self, name: str) -> None:
        """Move every slider to the preset, then apply it as a single state change."""
        preset = preset_for(name, self.view.settings)
        self._move_sliders(preset)
        self.update(settings=preset)

    def apply_advice(self, tip: Advice) -> None:
        """Make one suggested change (a setting step or a cleared fault) as a single state change."""
        target = tip.apply(self.view)
        self._move_sliders(target.settings)
        self.update(settings=target.settings, faults=target.faults)

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
        self._render_coach(metrics)
        self._render_drill()
        self._render_timeline(metrics)
        self._render_view()
        self.engine.set(self.view.render_params(metrics))

    def _render_coach(self, metrics: Metrics) -> None:
        """Pace summary, then the ranked suggestions (rebuilt only when they change)."""
        self.pace['pace'].text = format_duration(metrics.seconds_per_100)
        self.pace['swolf'].text = f'{metrics.swolf:.0f}'
        self.pace['speed'].text = f'{metrics.speed:.2f} m/s'
        self.pace['effort'].text = f'{metrics.effort:.0%}'
        tips = advice(self.view)
        layout = (tips, self.view.settings)
        if layout == self._advice_layout:
            return
        self._advice_layout = layout
        self.advice_list.clear()
        with self.advice_list:
            if not tips:
                ui.label('Nothing big left to fix at this stroke rate.').classes('lc-cue lc-cue-empty')
            for rank, tip in enumerate(tips, start=1):
                with ui.element('div').classes('lc-tip'):
                    ui.label(str(rank)).classes('lc-tip-rank')
                    with ui.element('div').classes('lc-tip-text'):
                        ui.label(tip.title).classes('lc-tip-title')
                        detail = change_text(self.view.settings, tip.settings) if tip.settings else tip.cue
                        ui.label(detail).classes('lc-tip-detail')
                        if tip.settings:
                            ui.label(tip.cue).classes('lc-tip-detail lc-tip-cue')
                    with ui.element('div').classes('lc-tip-side'):
                        saving = ui.label(f'−{tip.seconds_per_100:.1f} s').classes('lc-tip-gain')
                        saving.tooltip('Estimated time saved per 100 m')
                        apply = ui.button('Apply', on_click=lambda t=tip: self.apply_advice(t))
                        apply.props(f'flat dense no-caps aria-label="Apply: {tip.title}"').classes('lc-tip-apply')

    def _render_drill(self) -> None:
        """Explain the selected drill and name it on the stage."""
        drill = self.view.drill
        hint = DRILLS[drill].hint
        self.drill_hint.text = hint if drill == 'off' else f'{hint} Estimates stay on the full stroke.'
        self.brand.text = BRAND if drill == 'off' else f'{DRILLS[drill].label} drill'

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
            self.second_view.props(f'fps={60 if v.split else 1}')
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
            button.props(f'aria-pressed={str(name == active).lower()}')
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
        count = sum(not FAULTS[key].good for key in active)
        self.fault_badge.text = f'{count} on' if count else 'Clean'
        self.fault_badge.classes(replace='lc-badge lc-badge-fault' if count else 'lc-badge')
        self.clear_faults.set_visibility(bool(active))
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
                hint = 'Switch on a fault, a good-form cue or paddles to see how it changes the stroke.'
                ui.label(hint).classes('lc-cue lc-cue-empty')
            for key, fault in FAULTS.items():
                if key in active:
                    with ui.element('div').classes('lc-cue'):
                        ui.label(f'{fault.label}: ').classes('lc-cue-name')
                        ui.label(fault.cue).classes('inline')

    def _render_stats(self, metrics: Metrics, context: str = '') -> None:
        """Fill in the estimate tiles and colour the hold banner."""
        self.estimate_title.text = context
        tone = 'lc-good' if metrics.holding else 'lc-bad'
        self.stats['dps'].text = f'{metrics.distance_per_stroke:.2f} m'
        self.stats['spl'].text = f'{metrics.strokes_per_25:.1f}'
        self.stats['t25'].text = format_duration(metrics.seconds_per_25)
        self.stats['carry'].text = f'{metrics.momentum:.0%}'
        self.stats['dps'].classes(replace=f'lc-stat-value {tone}')
        self.hold_banner.classes(replace=f'lc-hold {tone}')
        self.hold_icon.name = 'check_circle' if metrics.holding else 'warning'
        self.hold_text.text = 'Hand hold' if metrics.holding else 'Hand slipping'

    def _render_timeline(self, metrics: Metrics) -> None:
        """Size the phase segments: recovery moves with stroke rate, a heavy felt load slows the
        hand under water and shortens the recovery, and spinning arms squeeze the pull."""
        s = self.view.settings
        faults = self.view.faults
        feel = felt_load(metrics.hold_quality, s.drive / 100, hand_area(faults))
        bounds = timeline_boundaries(path_length(s.rate), 'rushing' in faults, s.glide, feel, 'earlyexit' in faults)
        starts = (0.0, *bounds, 1.0)
        if starts == self._segment_layout:
            return
        self._segment_layout = starts
        for segment, (start, end) in zip(self.segments, pairwise(starts), strict=True):
            segment.style(f'left:{start * 100:.2f}%; width:{(end - start) * 100:.2f}%')
            if end - start < NARROW_SEGMENT:
                segment.classes(add='lc-seg-narrow')
            else:
                segment.classes(remove='lc-seg-narrow')


class RaceMode:
    """Independent lane settings and a browser-owned race clock, on the same page."""

    def __init__(self, studio_view: Callable[[], ViewState], show_estimates: Callable[[Metrics, str], None]) -> None:
        self.studio_view = studio_view
        self.show_estimates = show_estimates
        self.engine = RaceEngine()
        self.swimmers = [ViewState(settings=PRESETS[name]) for name in ('Long power', 'Short slipping')]
        self.distance = 50
        self.count = 2
        self.selected = 0
        self.applying = False
        self.scenes: list[dict[str, Any]] = []
        self.scene_elements: list[ui.scene] = []
        self.names: list[ui.label] = []
        self.estimates: list[ui.label] = []
        self.sliders: dict[str, ui.slider] = {}
        self.values: dict[str, ui.label] = {}
        self._last_config: RaceConfig | None = None

    def config(self) -> RaceConfig:
        return RaceConfig(tuple(self.swimmers[: self.count]), self.distance)

    def build(self) -> None:
        with ui.element('div').classes('lc-race-stage'):
            with ui.element('div').classes('lc-race-heading'):
                with ui.column().classes('gap-0'):
                    ui.label('Race lab').classes('lc-title')
                    ui.label('Estimated race / continuous swim').classes('lc-subtitle')
                with ui.column().classes('items-end gap-0'):
                    ui.label('Ready').classes('lc-race-status')
                    ui.label('0.00 s').classes('lc-race-clock')
            with ui.element('div').classes('lc-race-lanes') as self.lanes:
                for i, key in enumerate(('a', 'b')):
                    with ui.element('div').classes(f'lc-race-lane lc-race-lane-{key}') as lane:
                        if i == 1:
                            self.second_lane = lane
                        with ui.element('div').classes('lc-race-lane-title'):
                            ui.label(f'Swimmer {key.upper()}').classes(f'lc-lane-tag lc-lane-{key}')
                            self.names.append(ui.label().classes('lc-race-setup-name'))
                            self.estimates.append(ui.label().classes('lc-subtitle'))
                        scene = ui.scene(
                            width=600,
                            height=550,
                            grid=False,
                            background_color=PALETTE.background,
                            fps=60,
                            camera=ui.scene.perspective_camera(fov=42),
                        )
                        with scene:
                            palette = replace(PALETTE, cap=PALETTE.hold if i == 0 else PALETTE.patch)
                            ids = SwimmerBuilder(palette=palette).build()
                        scene.move_camera(0.3, -2.5, 1.8, -0.3, 0, -0.15, duration=0)
                        self.scenes.append({'id': scene.id, 'ids': ids})
                        self.scene_elements.append(scene)
            self._build_board()
        self._build_panel()
        self._render()

    def _build_board(self) -> None:
        with ui.element('div').classes('lc-race-board'):
            for i, key in enumerate(('a', 'b')):
                with ui.element('div').classes('lc-race-result') as row:
                    if i == 1:
                        self.second_result = row
                    ui.label(key.upper()).classes(f'lc-lane-tag lc-lane-{key}')
                    with (
                        ui.element('div')
                        .classes(f'lc-race-track lc-race-track-{key}')
                        .props(f'role=progressbar aria-label="Swimmer {key.upper()} distance" aria-valuemin=0')
                    ):
                        ui.element('div').classes(f'lc-race-fill lc-race-fill-{key}')
                    ui.label().classes(f'lc-race-metres lc-race-metres-{key}')
                    ui.label().classes(f'lc-race-time lc-race-time-{key}')
                    ui.label().classes(f'lc-race-place lc-race-place-{key}')
            with ui.row().classes('lc-race-transport'):
                with (
                    ui.button(on_click=lambda: self.engine.call('toggle'))
                    .props('no-caps unelevated')
                    .classes('lc-race-play')
                ):
                    ui.label('Start race').classes('lc-race-play-label')
                ui.button('Reset race', icon='restart_alt', on_click=lambda: self.engine.call('reset')).props(
                    'flat no-caps'
                )
                ui.element('div').classes('lc-spacer')
                ui.toggle(
                    {speed: f'{speed:g}x' for speed in RACE_PLAYBACK_SPEEDS},
                    value=1.0,
                    on_change=lambda e: self.set_speed(e.value),
                ).props('no-caps').tooltip('Race playback speed; finish times stay in simulated seconds')
                LongCatchPage._icon_button(
                    'center_focus_strong', 'Reset race cameras', lambda: self.engine.call('resetCamera')
                )
            ui.label().classes('lc-race-summary').props('aria-live=polite')

    def _build_panel(self) -> None:
        with ui.element('div').classes('lc-panel'):
            with ui.element('div').classes('lc-card'):
                section_title('Race setup')
                ui.toggle(
                    {d: f'{d} m' for d in RACE_DISTANCES},
                    value=self.distance,
                    on_change=lambda e: self.change_distance(e.value),
                ).props('no-caps spread').classes('lc-segmented').tooltip('Race distance')
                ui.toggle(
                    {1: 'Solo', 2: 'Two swimmers'},
                    value=self.count,
                    on_change=lambda e: self.change_count(e.value),
                ).props('no-caps spread').classes('lc-segmented q-mt-sm')
                ui.label('Changing a setup resets the race. Leaving this tab pauses it.').classes('lc-race-help')
            with ui.element('div').classes('lc-card'):
                self.editor_title = section_title('Configure swimmer A')
                self.lane_toggle = (
                    ui.toggle({0: 'Swimmer A', 1: 'Swimmer B'}, value=0, on_change=lambda e: self.select_lane(e.value))
                    .props('no-caps spread')
                    .classes('lc-segmented')
                )
                self.preset = (
                    ui.select(
                        list(PRESETS),
                        label='Race preset',
                        value='Long power',
                        on_change=lambda e: self.preset_changed(e.value),
                    )
                    .props('outlined dense options-dense')
                    .classes('w-full q-mt-md')
                )
                with ui.row().classes('lc-race-copy'):
                    ui.button('Use studio setup', on_click=self.copy_studio).props('flat dense no-caps').tooltip(
                        'Replace the selected swimmer with the studio stroke and faults'
                    )
                    self.copy_button = ui.button('Copy A to B', on_click=self.copy_lane).props('flat dense no-caps')
                    self.copy_button.tooltip('Copy the selected swimmer to the other lane')
                self.sliders, self.values = stroke_controls(
                    self.swimmers[0].settings, self.slider_changed, prefix='Race '
                )
                self.fault_select = (
                    ui.select(
                        {key: fault.label for key, fault in FAULTS.items()},
                        multiple=True,
                        value=[],
                        label='Race stroke faults',
                        on_change=lambda e: self.faults_changed(e.value),
                    )
                    .props('outlined dense use-chips options-dense')
                    .classes('w-full q-mt-md')
                )

    def start(self) -> None:
        self.engine.start(self.scenes, self.config().render_params())

    def set_active(self, active: bool) -> None:
        for i, scene in enumerate(self.scene_elements):
            scene.props(f'fps={60 if active and i < self.count else 1}')
        self.engine.call('setActive', active)

    def set_speed(self, value: Any) -> None:
        if value in RACE_PLAYBACK_SPEEDS:
            self.engine.call('setSpeed', value)

    def change_distance(self, value: Any) -> None:
        if value not in RACE_DISTANCES:
            return
        self.distance = value
        self._render()

    def change_count(self, value: Any) -> None:
        if value not in (1, 2):
            return
        self.count = value
        if value == 1:
            self.selected = 0
        self.second_lane.set_visibility(value == 2)
        self.second_result.set_visibility(value == 2)
        self.scene_elements[1].props(f'fps={60 if value == 2 else 1}')
        self.lanes.classes(add='lc-race-solo' if value == 1 else '', remove='lc-race-solo' if value == 2 else '')
        LongCatchPage._enable(self.lane_toggle, value == 2)
        LongCatchPage._enable(self.copy_button, value == 2)
        self._render()

    def select_lane(self, value: Any) -> None:
        if not self.applying and value in (0, 1):
            self.selected = value
            self._render_editor()

    def preset_changed(self, name: str | None) -> None:
        if not self.applying and name is not None:
            view = self.swimmers[self.selected]
            self.swimmers[self.selected] = replace(view, settings=preset_for(name, view.settings))
            self._render()

    def slider_changed(self, spec: SliderSpec, raw: Any) -> None:
        value = bounded_number(raw, *SETTING_RANGES[spec.key], spec.step)
        if not self.applying and value is not None:
            view = self.swimmers[self.selected]
            self.swimmers[self.selected] = replace(view, settings=view.settings.with_values(**{spec.key: value}))
            self._render()

    def faults_changed(self, values: list[str]) -> None:
        if not self.applying:
            self.swimmers[self.selected] = replace(self.swimmers[self.selected], faults=frozenset(values))
            self._render()

    def copy_studio(self) -> None:
        source = self.studio_view()
        self.swimmers[self.selected] = replace(
            self.swimmers[self.selected], settings=source.settings, faults=source.faults
        )
        self._render()

    def copy_lane(self) -> None:
        self.swimmers[1 - self.selected] = replace(self.swimmers[self.selected])
        self._render()

    def _render_editor(self) -> None:
        view = self.swimmers[self.selected]
        self.applying = True
        try:
            self.lane_toggle.value = self.selected
            self.preset.value = matching_preset(view.settings)
            self.fault_select.value = sorted(view.faults)
            for spec in SLIDERS:
                value = getattr(view.settings, spec.key)
                self.sliders[spec.key].value = value
                self.values[spec.key].text = f'{value}{spec.unit}'
        finally:
            self.applying = False
        self.editor_title.text = f'Configure swimmer {"B" if self.selected else "A"}'
        self.editor_title.classes(replace=f'lc-section-title lc-lane-{"b" if self.selected else "a"}')
        self.preset.props(f'display-value="{matching_preset(view.settings) or "Custom"}"')
        self.copy_button.text = 'Copy B to A' if self.selected else 'Copy A to B'
        self.show_estimates(view.metrics(), f'Swimmer {"B" if self.selected else "A"} estimates')

    def _render(self) -> None:
        for i, view in enumerate(self.swimmers):
            self.names[i].text = matching_preset(view.settings) or 'Custom'
            metrics = view.metrics()
            finish = metrics.seconds_per_25 * self.distance / 25
            speed = 25 / metrics.seconds_per_25
            self.estimates[
                i
            ].text = (
                f'{speed:.2f} m/s / {metrics.distance_per_stroke:.2f} m per stroke / Est. {format_duration(finish)}'
            )
        self._render_editor()
        config = self.config()
        if config != self._last_config:
            self._last_config = config
            self.engine.set(config.render_params())


@ui.page('/')
async def index() -> None:
    """Build a fresh page, with its own state, for each browser tab."""
    if hosted():
        ui.link('Sign out', '/logout').classes('self-end')
    page = LongCatchPage()
    page.build()
    await page.start()
