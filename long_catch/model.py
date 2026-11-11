"""Pure stroke model: settings, phases, timing, and coaching estimates.

Everything here is UI-free so it can be unit tested. All outputs are coaching
estimates, not measured, EMG, force, or medical data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Literal

# --- View options: each Literal is paired with the tuple the UI iterates over ---

Emphasis = Literal['back', 'triceps', 'core', 'balanced']
EMPHASES: tuple[Emphasis, ...] = ('back', 'triceps', 'core', 'balanced')
ViewAngle = Literal['top', 'side', 'front', 'below']
VIEW_ANGLES: tuple[ViewAngle, ...] = ('top', 'side', 'front', 'below')
Trail = Literal['off', 'hands', 'feet', 'both']
TRAILS: tuple[Trail, ...] = ('off', 'hands', 'feet', 'both')

PLAYBACK_SPEEDS: tuple[float, ...] = (0.25, 0.5, 1.0)
TRAIL_SECONDS = (0.5, 5.0)  # min and max ghost-trail length

# Hold quality at or above this reads as "holding water" in the UI.
HOLDING_THRESHOLD = 0.7


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limit ``value`` to the closed range [minimum, maximum]."""
    return max(minimum, min(value, maximum))


class Phase(IntEnum):
    """Broad steps of one arm's stroke, in the order they happen."""

    ENTRY = 0
    CATCH = 1
    PULL = 2
    FINISH = 3
    RECOVERY = 4

    @property
    def label(self) -> str:
        """Human-readable name shown in the HUD and timeline."""
        return PHASE_LABELS[self]


PHASE_LABELS: dict[Phase, str] = {
    Phase.ENTRY: 'Entry & reach',
    Phase.CATCH: 'Catch',
    Phase.PULL: 'Pull',
    Phase.FINISH: 'Finish',
    Phase.RECOVERY: 'Recovery',
}

# Fixed step boundaries as fractions of one arm cycle. The recovery start
# (hand exit) depends on path length; see `exit_phase`.
CATCH_START = 0.12
PULL_START = 0.30
FINISH_START = 0.62


def path_length(stroke_rate: float) -> float:
    """1.0 = long underwater path (low rate), 0.0 = compact path (high rate)."""
    return clamp((60.0 - stroke_rate) / 22.0, 0.0, 1.0)


def exit_phase(length: float) -> float:
    """Phase where the hand leaves the water; longer strokes stay in longer."""
    return 0.68 + 0.08 * clamp(length, 0.0, 1.0)


def phase_boundaries(length: float) -> tuple[float, float, float, float]:
    """Start of catch, pull, finish, and recovery for a given path length."""
    return CATCH_START, PULL_START, FINISH_START, exit_phase(length)


def phase_to_step(phase: float, length: float = 0.5) -> Phase:
    """Map an arm phase (wrapped into [0, 1)) to its broad stroke step."""
    p = phase % 1.0
    step = Phase.ENTRY
    later_steps = (Phase.CATCH, Phase.PULL, Phase.FINISH, Phase.RECOVERY)
    for next_step, start in zip(later_steps, phase_boundaries(length), strict=True):
        if p < start:
            break
        step = next_step
    return step


def arm_phases(phase: float) -> tuple[float, float]:
    """Right and left arm phases; the arms are half a cycle apart."""
    return phase % 1.0, (phase + 0.5) % 1.0


def cycle_duration(stroke_rate: float) -> float:
    """Seconds for one right-and-left cycle; every hand entry is one stroke."""
    if stroke_rate <= 0:
        raise ValueError('stroke_rate must be positive')
    return 120.0 / stroke_rate


def format_duration(seconds: float) -> str:
    """Format seconds as ``'12.3 s'`` under a minute, else ``'m:ss.s'``; ``'–'`` if invalid."""
    if not math.isfinite(seconds) or seconds < 0:
        return '–'
    if round(seconds, 1) < 60:
        return f'{seconds:.1f} s'
    minutes, rest = divmod(round(seconds, 1), 60)
    return f'{int(minutes)}:{rest:04.1f}'


@dataclass(frozen=True, slots=True)
class Metrics:
    """Coaching estimates for one stroke setup. None of these are measured."""

    hold_quality: float  # 0–1: how well the hand holds water
    distance_per_stroke: float  # metres per hand entry
    strokes_per_25: float
    seconds_per_25: float

    @property
    def holding(self) -> bool:
        """True when the hold is good enough to call it "holding water"."""
        return self.hold_quality >= HOLDING_THRESHOLD


def estimate_metrics(
    catch_quality: float,
    slip: float,
    drive_balance: float,
    stroke_rate: float,
    drag: float = 0.0,
) -> Metrics:
    """Estimate stroke efficiency from fractional inputs (0–1) and a rate in spm.

    Drive only scales the benefit of a good hold, so it cannot rescue a poor
    catch or heavy slip. Slip also costs distance directly, rates above 56 spm
    shorten the stroke, and ``drag`` (from faults) removes a fixed fraction.
    """
    hold_quality = clamp(0.6 * catch_quality + 0.4 * (1.0 - slip), 0.0, 1.0)
    # Drive multiplies the hold rather than adding to it.
    connection = 0.7 + 0.3 * drive_balance
    rate_penalty = max(0.0, stroke_rate - 56.0) / 80.0
    distance_per_stroke = clamp(
        (0.55 + 0.75 * hold_quality * connection - 0.40 * slip - rate_penalty) * (1.0 - drag),
        0.45,
        1.40,
    )
    strokes_per_25 = 25.0 / distance_per_stroke
    return Metrics(
        hold_quality=hold_quality,
        distance_per_stroke=distance_per_stroke,
        strokes_per_25=strokes_per_25,
        seconds_per_25=strokes_per_25 * 60.0 / stroke_rate,
    )


@dataclass(frozen=True, slots=True)
class Fault:
    """A common stroke error that can be switched on to show its shape and cost."""

    label: str
    hint: str  # what the fault looks like
    cue: str  # coaching cue that fixes it
    drag: float = 0.0  # fraction of distance per stroke lost
    slip: float = 0.0  # added to slip (0–1)
    catch: float = 0.0  # removed from catch quality (0–1)


FAULTS: dict[str, Fault] = {
    'crossover': Fault(
        'Crossover',
        'Hands enter past the centre line, pushing the body off line.',
        'Enter in line with your shoulder, not your nose.',
        drag=0.05,
    ),
    'overrotation': Fault(
        'Over-rotation',
        'The body rolls far past 45°, wasting time and balance.',
        'Roll to about 45° and keep the head still.',
        drag=0.05,
    ),
    'overreach': Fault(
        'Over-extension',
        'The arm locks straight, shoulder shrugs, and the hand pauses up at the front.',
        'Reach long but soft, then tip the fingertips down straight away.',
        drag=0.06,
    ),
    'flathips': Fault(
        'Flat hips',
        'The shoulders do all the rotating while the hips stay flat, so the core cannot connect the pull.',
        'Rotate hips and shoulders together, as one unit.',
        drag=0.04,
    ),
    'sinking': Fault(
        'Sinking legs',
        'Head and chest lift up while the hips and legs sink low, dragging through the water.',
        'Look at the floor and press the chest down; the hips will rise.',
        drag=0.09,
    ),
    'snaking': Fault(
        'Snaking',
        'Hips and legs sway side to side behind the chest.',
        'Keep the hips under the chest and kick straight down the lane.',
        drag=0.07,
    ),
    'kneekick': Fault(
        'Knee kick',
        'Bicycle-style kick bent from the knees instead of driven from the hips.',
        'Kick from the hips with long, loose legs.',
        drag=0.05,
    ),
    'rushing': Fault(
        'Spinning arms',
        'Arms rush through the pull faster than the hand can hold water, so it slips.',
        'Slow the hand down until you feel the water, then accelerate.',
        slip=0.35,
        catch=0.25,
    ),
}

# With 'rushing' on, the underwater part of the cycle is squeezed into this
# fraction of its normal time, so the hand visibly hurries through the pull.
RUSH = 0.72


def fault_drag(faults: frozenset[str]) -> float:
    """Combined fractional distance loss from drag-type faults."""
    keep = 1.0
    for key in faults:
        keep *= 1.0 - FAULTS[key].drag
    return 1.0 - keep


def timeline_boundaries(length: float, rushed: bool = False) -> tuple[float, float, float, float]:
    """Phase boundaries as seen on screen; a rushed stroke squeezes the underwater part."""
    bounds = phase_boundaries(length)
    return tuple(b * RUSH for b in bounds) if rushed else bounds


def highlight_intensity(hold_quality: float, drive_balance: float) -> float:
    """Muscle-overlay strength (0.15–1.0); a strong glow needs both hold and drive."""
    return 0.15 + 0.85 * (clamp(hold_quality, 0.0, 1.0) * clamp(drive_balance, 0.0, 1.0)) ** 1.5


# Inclusive slider ranges; StrokeSettings rejects anything outside them.
SETTING_RANGES: dict[str, tuple[int, int]] = {
    'rate': (32, 72),
    'catch': (0, 100),
    'roll': (20, 62),
    'slip': (0, 100),
    'entry': (0, 40),
    'drive': (0, 100),
    'kick': (0, 100),
}


@dataclass(frozen=True, slots=True)
class StrokeSettings:
    """User-facing settings: percentages 0–100, rate in spm, roll and entry in degrees."""

    rate: int = 38
    catch: int = 92
    roll: int = 46
    slip: int = 8
    entry: int = 5
    drive: int = 85
    kick: int = 45

    def __post_init__(self) -> None:
        for name, (lo, hi) in SETTING_RANGES.items():
            value = getattr(self, name)
            if not lo <= value <= hi:
                raise ValueError(f'{name}={value} outside {lo}–{hi}')

    def with_values(self, **changes: int) -> StrokeSettings:
        """Return a validated copy with the given fields changed."""
        return replace(self, **changes)

    def metrics(self) -> Metrics:
        """Estimates for these settings alone, ignoring any faults."""
        return estimate_metrics(self.catch / 100, self.slip / 100, self.drive / 100, self.rate)


@dataclass(frozen=True, slots=True)
class ViewState:
    """Everything one browser tab shows: stroke settings plus view options.

    Immutable; the app replaces it on every change, and the constructor
    validates every field.
    """

    settings: StrokeSettings = field(default_factory=StrokeSettings)
    emphasis: Emphasis = 'back'
    playing: bool = True
    playback: float = 1.0
    faults: frozenset[str] = frozenset()
    split: bool = False
    angle: ViewAngle = 'top'
    trail: Trail = 'off'
    trail_seconds: float = 1.5

    def __post_init__(self) -> None:
        if self.emphasis not in EMPHASES:
            raise ValueError(f'unknown emphasis {self.emphasis!r}')
        if self.playback not in PLAYBACK_SPEEDS:
            raise ValueError(f'unsupported playback speed {self.playback!r}')
        if self.angle not in VIEW_ANGLES:
            raise ValueError(f'unknown view angle {self.angle!r}')
        if self.trail not in TRAILS:
            raise ValueError(f'unknown trail {self.trail!r}')
        if not TRAIL_SECONDS[0] <= self.trail_seconds <= TRAIL_SECONDS[1]:
            raise ValueError(f'trail_seconds={self.trail_seconds} outside {TRAIL_SECONDS}')
        unknown = set(self.faults) - set(FAULTS)
        if unknown:
            raise ValueError(f'unknown faults {sorted(unknown)}')

    def with_fault(self, key: str, active: bool) -> ViewState:
        """Return a copy with fault ``key`` switched on or off."""
        faults = self.faults | {key} if active else self.faults - {key}
        return replace(self, faults=frozenset(faults))

    def effective_hold(self) -> tuple[float, float]:
        """Catch quality and slip as fractions after hold-type faults."""
        s = self.settings
        catch = s.catch / 100 - sum(FAULTS[k].catch for k in self.faults)
        slip = s.slip / 100 + sum(FAULTS[k].slip for k in self.faults)
        return clamp(catch, 0.0, 1.0), clamp(slip, 0.0, 1.0)

    def metrics(self) -> Metrics:
        """Estimates for the settings with every active fault applied."""
        s = self.settings
        catch, slip = self.effective_hold()
        return estimate_metrics(catch, slip, s.drive / 100, s.rate, fault_drag(self.faults))

    def render_params(self, metrics: Metrics | None = None) -> dict[str, float | str | bool | list[str]]:
        """Parameters for the browser animation loop (fractions, not percentages)."""
        s = self.settings
        m = metrics if metrics is not None else self.metrics()
        length = path_length(s.rate)
        catch, slip = self.effective_hold()
        return {
            'rate': s.rate,
            'catch': catch,
            'slip': slip,
            'drive': s.drive / 100,
            'kick': s.kick / 100,
            'entry': s.entry,
            'roll': s.roll,
            'emphasis': self.emphasis,
            'playing': self.playing,
            'playback': self.playback,
            'length': length,
            'exit': exit_phase(length),
            'faults': sorted(self.faults),
            'rush': RUSH if 'rushing' in self.faults else 1.0,
            'trail': self.trail,
            'trailSeconds': self.trail_seconds,
            'intensity': highlight_intensity(m.hold_quality, s.drive / 100),
            'speed': m.distance_per_stroke * s.rate / 60.0,  # metres per second
        }


# Example strokes, ordered from most to least efficient (keys 1–4 in the UI).
PRESETS: dict[str, StrokeSettings] = {
    'Long power': StrokeSettings(rate=38, catch=92, roll=46, slip=8, drive=85, kick=45),
    'Long light': StrokeSettings(rate=40, catch=88, roll=44, slip=10, drive=70, kick=25),
    'Compact connected': StrokeSettings(rate=48, catch=82, roll=42, slip=14, drive=68, kick=60),
    'Short slipping': StrokeSettings(rate=54, catch=42, roll=34, slip=62, drive=35, kick=35),
}


def matching_preset(settings: StrokeSettings) -> str | None:
    """Name of the preset these settings equal, or None for a custom stroke."""
    return next((name for name, preset in PRESETS.items() if preset == settings), None)
