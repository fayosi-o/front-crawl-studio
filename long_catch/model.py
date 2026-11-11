"""Pure stroke model: settings, phases, timing, and coaching estimates.

Everything here is UI-free so it can be unit tested. All outputs are coaching
estimates, not measured, EMG, force, or medical data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Literal

Emphasis = Literal['back', 'triceps', 'core', 'balanced']
EMPHASES: tuple[Emphasis, ...] = ('back', 'triceps', 'core', 'balanced')
PLAYBACK_SPEEDS: tuple[float, ...] = (0.25, 0.5, 1.0)
HOLDING_THRESHOLD = 0.7


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


class Phase(IntEnum):
    ENTRY = 0
    CATCH = 1
    PULL = 2
    FINISH = 3
    RECOVERY = 4

    @property
    def label(self) -> str:
        return PHASE_LABELS[self]


PHASE_LABELS: dict[Phase, str] = {
    Phase.ENTRY: 'Entry & reach',
    Phase.CATCH: 'Catch',
    Phase.PULL: 'Pull',
    Phase.FINISH: 'Finish',
    Phase.RECOVERY: 'Recovery',
}

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
    if not math.isfinite(seconds) or seconds < 0:
        return '–'
    if round(seconds, 1) < 60:
        return f'{seconds:.1f} s'
    minutes, rest = divmod(round(seconds, 1), 60)
    return f'{int(minutes)}:{rest:04.1f}'


@dataclass(frozen=True, slots=True)
class Metrics:
    hold_quality: float
    distance_per_stroke: float
    strokes_per_25: float
    seconds_per_25: float

    @property
    def holding(self) -> bool:
        return self.hold_quality >= HOLDING_THRESHOLD


def estimate_metrics(
    catch_quality: float,
    slip: float,
    drive_balance: float,
    stroke_rate: float,
) -> Metrics:
    """BUILD_SPEC section 12. Drive cannot rescue a poor catch or heavy slip."""
    hold_quality = clamp(0.6 * catch_quality + 0.4 * (1.0 - slip), 0.0, 1.0)
    connection = 0.7 + 0.3 * drive_balance
    rate_penalty = max(0.0, stroke_rate - 56.0) / 80.0
    distance_per_stroke = clamp(
        0.55 + 0.75 * hold_quality * connection - 0.40 * slip - rate_penalty,
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


def highlight_intensity(hold_quality: float, drive_balance: float) -> float:
    return 0.15 + 0.85 * (clamp(hold_quality, 0.0, 1.0) * clamp(drive_balance, 0.0, 1.0)) ** 1.5


SETTING_RANGES: dict[str, tuple[int, int]] = {
    'rate': (32, 72),
    'catch': (0, 100),
    'roll': (20, 62),
    'slip': (0, 100),
    'drive': (0, 100),
    'kick': (0, 100),
}


@dataclass(frozen=True, slots=True)
class StrokeSettings:
    """User-facing settings: percentages 0–100, rate in spm, roll in degrees."""

    rate: int = 38
    catch: int = 92
    roll: int = 46
    slip: int = 8
    drive: int = 85
    kick: int = 45

    def __post_init__(self) -> None:
        for name, (lo, hi) in SETTING_RANGES.items():
            value = getattr(self, name)
            if not lo <= value <= hi:
                raise ValueError(f'{name}={value} outside {lo}–{hi}')

    def with_values(self, **changes: int) -> StrokeSettings:
        return replace(self, **changes)

    def metrics(self) -> Metrics:
        return estimate_metrics(self.catch / 100, self.slip / 100, self.drive / 100, self.rate)


@dataclass(frozen=True, slots=True)
class ViewState:
    settings: StrokeSettings = field(default_factory=StrokeSettings)
    emphasis: Emphasis = 'back'
    playing: bool = True
    playback: float = 1.0

    def __post_init__(self) -> None:
        if self.emphasis not in EMPHASES:
            raise ValueError(f'unknown emphasis {self.emphasis!r}')
        if self.playback not in PLAYBACK_SPEEDS:
            raise ValueError(f'unsupported playback speed {self.playback!r}')

    def render_params(self, metrics: Metrics | None = None) -> dict[str, float | str | bool]:
        """Parameters for the browser animation loop (fractions, not percentages)."""
        s = self.settings
        m = metrics if metrics is not None else s.metrics()
        length = path_length(s.rate)
        return {
            'rate': s.rate,
            'catch': s.catch / 100,
            'slip': s.slip / 100,
            'drive': s.drive / 100,
            'kick': s.kick / 100,
            'roll': s.roll,
            'emphasis': self.emphasis,
            'playing': self.playing,
            'playback': self.playback,
            'length': length,
            'exit': exit_phase(length),
            'intensity': highlight_intensity(m.hold_quality, s.drive / 100),
            'speed': m.distance_per_stroke * s.rate / 60.0,
        }


PRESETS: dict[str, StrokeSettings] = {
    'Long power': StrokeSettings(rate=38, catch=92, roll=46, slip=8, drive=85, kick=45),
    'Long light': StrokeSettings(rate=40, catch=88, roll=44, slip=10, drive=70, kick=25),
    'Compact connected': StrokeSettings(rate=48, catch=82, roll=42, slip=14, drive=68, kick=60),
    'Short slipping': StrokeSettings(rate=54, catch=42, roll=34, slip=62, drive=35, kick=35),
}


def matching_preset(settings: StrokeSettings) -> str | None:
    """Name of the preset these settings equal, or None for a custom stroke."""
    return next((name for name, preset in PRESETS.items() if preset == settings), None)
