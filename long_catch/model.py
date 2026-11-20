"""Pure stroke model: settings, phases, timing, faults, and stroke metrics.

Everything here is UI-free so it can be unit tested.
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
RACE_DISTANCES = (25, 50, 100)
RACE_PLAYBACK_SPEEDS = (1.0, 2.0, 4.0)

# Hold quality at or above this reads as "holding water" in the UI.
HOLDING_THRESHOLD = 0.7

# Momentum between strokes: the body coasts on a passive-drag time constant once
# the hand stops driving, so long gaps between strokes bleed speed that the next
# catch must win back from slower water.
GLIDE_DECAY_S = 1.6  # seconds for coasting speed to fall to 1/e
PROPULSIVE_S = 0.85  # seconds of each stroke in which the hand drives the body

# Below this rate the stroke lengthens: a slow, patient stroke reaches further and
# holds the water for longer, worth up to LONG_STROKE_M extra metres at the slowest rate.
LONG_STROKE_FROM = 42.0
LONG_STROKE_SPAN = 20.0
LONG_STROKE_M = 1.2


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limit ``value`` to the closed range [minimum, maximum]."""
    return max(minimum, min(value, maximum))


class Phase(IntEnum):
    """Broad steps of one arm's stroke, in the order they happen."""

    ENTRY = 0
    CATCH = 1
    PULL = 2
    PUSH = 3
    FINISH = 4
    RECOVERY = 5

    @property
    def label(self) -> str:
        """Human-readable name shown in the HUD and timeline."""
        return PHASE_LABELS[self]


PHASE_LABELS: dict[Phase, str] = {
    Phase.ENTRY: 'Entry & reach',
    Phase.CATCH: 'Catch',
    Phase.PULL: 'Pull',
    Phase.PUSH: 'Push',
    Phase.FINISH: 'Finish',
    Phase.RECOVERY: 'Recovery',
}

# Fixed step boundaries as fractions of one arm cycle. The recovery start
# (hand exit) depends on path length; see `exit_phase`.
CATCH_START = 0.12
PULL_START = 0.30
PUSH_START = 0.50
FINISH_START = 0.66
FRONT_GLIDE_SHIFT = 0.08  # maximum timing shift, as a fraction of the full arm cycle


def path_length(stroke_rate: float) -> float:
    """1.0 = long underwater path (low rate), 0.0 = compact path (high rate)."""
    return clamp((60.0 - stroke_rate) / 22.0, 0.0, 1.0)


def exit_phase(length: float) -> float:
    """Phase where the hand leaves the water; longer strokes stay in longer."""
    return 0.70 + 0.08 * clamp(length, 0.0, 1.0)


def phase_boundaries(length: float) -> tuple[float, ...]:
    """Start of catch, pull, push, finish, and recovery for a given path length."""
    return CATCH_START, PULL_START, PUSH_START, FINISH_START, exit_phase(length)


# Felt load. The water the hand pushes back pushes back on the palm and forearm, so through the
# pull the arm feels heavier, as if it were lifting a weight. Only the sensation grows (buoyancy
# and the estimates are unchanged), but the arm moves to it: the hand works more slowly through
# the heaviest water, speeds up out of the back as the load lets go, and the weightless recovery
# makes up the rest of the time, so the stroke rate holds. A slipping hand feels light and goes
# through almost unslowed.
LOAD_DWELL = 0.36  # extra time per unit of underwater path at full load with a full hold
LOAD_RELEASE = 0.75  # share of that time won back by the end of the push, as the load lets go


def felt_load(hold_quality: float, drive_balance: float) -> float:
    """Peak load (0–1) felt on the hand and forearm: the hold, connected to the body by the hips.

    Uses the same hold and hip connection as the estimates, so a stroke that holds water in the
    estimates also feels heavy in the arm.
    """
    return clamp(hold_quality, 0.0, 1.0) * (0.7 + 0.3 * clamp(drive_balance, 0.0, 1.0))


def load_profile(phase: float, exit: float) -> float:
    """Share (0–1) of the peak load felt at arm-path ``phase``.

    Nothing during the entry and reach or in the air; the load builds as the forearm sets at the
    catch, is heaviest as the hand passes under the shoulder, and releases through the push.
    """
    x = (phase % 1.0 - CATCH_START) / (exit - CATCH_START)
    return math.sin(math.pi * x) ** 2 if 0.0 < x < 1.0 else 0.0


def loaded_time(phase: float, exit: float, feel: float = 0.0, rush: float = 1.0) -> float:
    """Clock phase at which the arm reaches path ``phase`` (at or before the exit).

    The time the hand spends at each part of its underwater path grows with the load felt there
    and shrinks again as the load lets go through the push, so the catch keeps its time, the hand
    is slowest under the shoulder and fastest at the exit, and every point still arrives later.
    ``rush`` below 1 (spinning arms) squeezes the whole underwater part. The recovery fills the
    rest of the cycle.
    """
    span = exit - CATCH_START
    x = clamp((phase - CATCH_START) / span, 0.0, 1.0)
    # Integral of load_profile, less the release (LOAD_RELEASE * x^2).
    held = span * (x / 2 - math.sin(2 * math.pi * x) / (4 * math.pi) - LOAD_RELEASE * x**3 / 3)
    return rush * (phase + LOAD_DWELL * clamp(feel, 0.0, 1.0) * held)


def phase_to_step(phase: float, length: float = 0.5) -> Phase:
    """Map an arm phase (wrapped into [0, 1)) to its broad stroke step."""
    p = phase % 1.0
    step = Phase.ENTRY
    later_steps = (Phase.CATCH, Phase.PULL, Phase.PUSH, Phase.FINISH, Phase.RECOVERY)
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


def stroke_phase(phase: float, glide: int = 50) -> float:
    """Map clock phase to arm-path phase, adjusting the front glide only."""
    p = phase % 1.0
    if p >= PULL_START:
        return p
    return p - FRONT_GLIDE_SHIFT * (glide - 50) / 50 * math.sin(math.pi * p / PULL_START) ** 2


def stroke_time(phase: float, glide: int = 50) -> float:
    """Clock phase at which an arm-path phase is reached (inverse of stroke_phase)."""
    p = phase % 1.0
    if p >= PULL_START or glide == 50:
        return p
    lo, hi = 0.0, PULL_START
    for _ in range(32):
        mid = (lo + hi) / 2
        if stroke_phase(mid, glide) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def glide_seconds(stroke_rate: float, glide: int = 50) -> float:
    """Unpropelled coast in each stroke: the time between one push ending and the next catch."""
    delay = stroke_time(CATCH_START, glide) - CATCH_START
    return max(0.0, 60.0 / stroke_rate - PROPULSIVE_S + delay * cycle_duration(stroke_rate))


def momentum_carry(stroke_rate: float, glide: int = 50) -> float:
    """Fraction of peak speed still carried when the next stroke catches (0–1).

    A low turnover leaves a long coast, so the next hand meets slower water
    and spends part of its pull re-accelerating the body. A higher turnover
    keeps the body and the water around it moving between strokes.
    """
    if stroke_rate <= 0:
        raise ValueError('stroke_rate must be positive')
    return math.exp(-glide_seconds(stroke_rate, glide) / GLIDE_DECAY_S)


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
    """Stroke metrics for one stroke setup."""

    hold_quality: float  # 0–1: how well the hand holds water
    distance_per_stroke: float  # metres per hand entry
    strokes_per_25: float
    seconds_per_25: float
    momentum: float = 1.0  # 0–1: speed carried into the next catch (see momentum_carry)

    @property
    def holding(self) -> bool:
        """True when the hold is good enough to call it "holding water"."""
        return self.hold_quality >= HOLDING_THRESHOLD

    @property
    def seconds_per_100(self) -> float:
        """Pace per 100 m at a steady speed (no dives or turns)."""
        return 4.0 * self.seconds_per_25

    @property
    def speed(self) -> float:
        """Average swimming speed in metres per second."""
        return 25.0 / self.seconds_per_25

    @property
    def swolf(self) -> float:
        """Strokes plus seconds for one 25 m length; lower is more efficient."""
        return self.strokes_per_25 + self.seconds_per_25


def estimate_metrics(
    catch_quality: float,
    slip: float,
    drive_balance: float,
    stroke_rate: float,
    drag: float = 0.0,
    glide: int = 50,
) -> Metrics:
    """Estimate stroke efficiency from fractional inputs (0–1) and a rate in spm.

    Drive only scales the benefit of a good hold, so it cannot rescue a poor
    catch or heavy slip. Slip also costs distance directly, rates above 56 spm
    shorten the stroke, rates below 42 spm lengthen it only as far as the hand
    holds water, low rates and longer glides lose momentum between strokes,
    and ``drag`` (from faults) removes a fixed fraction.
    """
    hold_quality = clamp(0.6 * catch_quality + 0.4 * (1.0 - slip), 0.0, 1.0)
    # Drive multiplies the hold rather than adding to it.
    connection = 0.7 + 0.3 * drive_balance
    rate_penalty = max(0.0, stroke_rate - 56.0) / 80.0
    reach = clamp((LONG_STROKE_FROM - stroke_rate) / LONG_STROKE_SPAN, 0.0, 1.0) ** 1.5
    momentum = momentum_carry(stroke_rate, glide)
    distance_per_stroke = clamp(
        (0.55 + 0.75 * hold_quality * connection - 0.40 * slip - rate_penalty + LONG_STROKE_M * reach * hold_quality)
        * (0.80 + 0.20 * momentum)
        * (1.0 - drag),
        0.45,
        2.20,
    )
    strokes_per_25 = 25.0 / distance_per_stroke
    return Metrics(
        hold_quality=hold_quality,
        distance_per_stroke=distance_per_stroke,
        strokes_per_25=strokes_per_25,
        seconds_per_25=strokes_per_25 * 60.0 / stroke_rate,
        momentum=momentum,
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
    'headlift': Fault(
        'Head lift',
        'The head lifts forward to breathe, so the chest rises, the hips drop and each breath stalls the stroke.',
        'Turn to breathe with one goggle in the water; the roll makes the room.',
        drag=0.06,
    ),
}

# With 'rushing' on, the underwater part of the cycle is squeezed into this
# fraction of its normal time, so the hand visibly hurries through the pull.
RUSH = 0.72

DrillName = Literal['off', 'catchup', 'single', 'fist']


@dataclass(frozen=True, slots=True)
class Drill:
    """A practice pattern the swimmer can demonstrate. Drills are visual only: estimates stay on the full stroke."""

    label: str
    hint: str  # what the drill isolates and what to watch for
    cycle_scale: float = 1.0  # cycle length relative to the full stroke at the same rate


DRILLS: dict[DrillName, Drill] = {
    'off': Drill('Full stroke', 'The full stroke at the chosen rate.'),
    'catchup': Drill(
        'Catch-up',
        'Each hand waits in front until the other arrives, so every pull starts from a long, steady line. '
        'Each arm keeps its normal speed, so turnover halves.',
        cycle_scale=2.0,
    ),
    'single': Drill(
        'One arm',
        'The left arm stays long in front while the right arm strokes. Watch the hips start the roll.',
    ),
    'fist': Drill(
        'Fist',
        'Closed hands leave the forearm to catch. Turn on Water pressure to see the load move up the arm.',
    ),
}


def fault_drag(faults: frozenset[str]) -> float:
    """Combined fractional distance loss from drag-type faults."""
    keep = 1.0
    for key in faults:
        keep *= 1.0 - FAULTS[key].drag
    return 1.0 - keep


def timeline_boundaries(length: float, rushed: bool = False, glide: int = 50, feel: float = 0.0) -> tuple[float, ...]:
    """Phase boundaries as seen on screen.

    A heavy felt load (``feel``) slows the hand under water and shortens the recovery; a rushed
    stroke squeezes the underwater part.
    """
    bounds = phase_boundaries(length)
    exit = bounds[-1]
    rush = RUSH if rushed else 1.0
    return tuple(stroke_time(loaded_time(b, exit, feel, rush), glide) for b in bounds)


def highlight_intensity(hold_quality: float, drive_balance: float) -> float:
    """Muscle-overlay strength (0.15–1.0); a strong glow needs both hold and drive."""
    return 0.15 + 0.85 * (clamp(hold_quality, 0.0, 1.0) * clamp(drive_balance, 0.0, 1.0)) ** 1.5


def waterline_pose(speed: float) -> tuple[float, float]:
    """Visual buoyancy targets in metres: body lift and extra hip drop.

    Pace provides a little dynamic support, not enough to lift the body out of
    the water. This illustrative response never feeds back into the estimates.
    """
    if not math.isfinite(speed) or speed < 0:
        raise ValueError('speed must be finite and non-negative')
    support = clamp((speed - 0.24) / 0.76, 0.0, 1.0)
    support = support * support * (3 - 2 * support)
    return -0.045 + 0.075 * support, 0.025 * (1 - support)


# Inclusive slider ranges; StrokeSettings rejects anything outside them.
SETTING_RANGES: dict[str, tuple[int, int]] = {
    'rate': (22, 72),
    'catch': (0, 100),
    'roll': (20, 62),
    'slip': (0, 100),
    'width': (0, 100),
    'depth': (0, 100),
    'entry': (0, 40),
    'drive': (0, 100),
    'kick': (0, 100),
    'beats': (2, 6),
    'glide': (0, 100),
    'breath': (2, 5),
}
# Settings that move in coarser steps than 1 (kicks per arm cycle: 2, 4, or 6).
SETTING_STEPS: dict[str, int] = {'beats': 2}


@dataclass(frozen=True, slots=True)
class StrokeSettings:
    """User-facing settings: percentages 0–100, rate in spm, roll and entry in degrees."""

    rate: int = 42
    catch: int = 92
    roll: int = 46
    slip: int = 8
    width: int = 35  # pull width: 0 = hand sweeps in under the body, 100 = wide of the shoulder line
    depth: int = 50  # pull depth: 0 = hand close to the body, 100 = deep, straighter arm
    entry: int = 5
    drive: int = 85
    kick: int = 45
    beats: int = 2  # kicks per arm cycle; the two-beat kick times the hip rotation
    glide: int = 50  # front-end timing: 0 = earlier catch, 50 = normal, 100 = longer glide
    breath: int = 3  # hand entries per breath: odd counts alternate sides, even counts breathe right

    def __post_init__(self) -> None:
        for name, (lo, hi) in SETTING_RANGES.items():
            value = getattr(self, name)
            if not lo <= value <= hi or (value - lo) % SETTING_STEPS.get(name, 1):
                raise ValueError(f'{name}={value} outside {lo}–{hi}')

    def with_values(self, **changes: int) -> StrokeSettings:
        """Return a validated copy with the given fields changed."""
        return replace(self, **changes)

    def metrics(self) -> Metrics:
        """Estimates for these settings alone, ignoring any faults."""
        return estimate_metrics(self.catch / 100, self.slip / 100, self.drive / 100, self.rate, glide=self.glide)


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
    pressure: bool = False
    drill: DrillName = 'off'

    def __post_init__(self) -> None:
        for name in ('playing', 'split', 'pressure'):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f'{name} must be true or false')
        if self.emphasis not in EMPHASES:
            raise ValueError(f'unknown emphasis {self.emphasis!r}')
        if self.drill not in DRILLS:
            raise ValueError(f'unknown drill {self.drill!r}')
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
        return estimate_metrics(catch, slip, s.drive / 100, s.rate, fault_drag(self.faults), s.glide)

    def render_params(self, metrics: Metrics | None = None) -> dict[str, int | float | str | bool | list[str]]:
        """Parameters for the browser animation loop (fractions, not percentages)."""
        s = self.settings
        m = metrics if metrics is not None else self.metrics()
        length = path_length(s.rate)
        catch, slip = self.effective_hold()
        speed = m.distance_per_stroke * s.rate / 60.0
        ride_height, hip_drop = waterline_pose(speed)
        return {
            'rate': s.rate,
            'catch': catch,
            'slip': slip,
            'drive': s.drive / 100,
            'kick': s.kick / 100,
            'beats': s.beats,
            'breath': s.breath,
            'drill': self.drill,
            'cycleScale': DRILLS[self.drill].cycle_scale,
            'frontGlide': FRONT_GLIDE_SHIFT * (s.glide - 50) / 50,
            'catchDelay': stroke_time(CATCH_START, s.glide) - CATCH_START,
            'width': s.width / 100,
            'depth': s.depth / 100,
            'entry': s.entry,
            'roll': s.roll,
            'emphasis': self.emphasis,
            'playing': self.playing,
            'playback': self.playback,
            'length': length,
            'exit': exit_phase(length),
            'faults': sorted(self.faults),
            'rush': RUSH if 'rushing' in self.faults else 1.0,
            'feel': felt_load(m.hold_quality, s.drive / 100),
            'trail': self.trail,
            'trailSeconds': self.trail_seconds,
            'pressure': self.pressure,
            'intensity': highlight_intensity(m.hold_quality, s.drive / 100),
            'speed': speed,  # metres per second, averaged over the cycle
            'momentum': m.momentum,
            # Share of each stroke spent coasting; the engine shapes the speed surge from it.
            'glide': glide_seconds(s.rate, s.glide) * s.rate / 60.0,
            'rideHeight': ride_height,
            'hipDrop': hip_drop,
        }


# Example strokes, ordered from most to least efficient (keys 1–4 in the UI).
# The first three are distance strokes built on a two- or four-beat kick.
PRESETS: dict[str, StrokeSettings] = {
    'Long power': StrokeSettings(rate=42, catch=92, roll=46, slip=8, width=35, drive=85, kick=45, beats=2),
    'Long light': StrokeSettings(rate=44, catch=88, roll=44, slip=10, width=40, drive=70, kick=30, beats=2),
    'Compact connected': StrokeSettings(rate=52, catch=82, roll=40, slip=14, width=30, drive=68, kick=55, beats=4),
    'Short slipping': StrokeSettings(rate=56, catch=42, roll=34, slip=62, width=85, drive=35, kick=40, beats=6),
}


def matching_preset(settings: StrokeSettings) -> str | None:
    """Name of the preset these settings equal, or None for a custom stroke."""
    return next((name for name, preset in PRESETS.items() if preset == settings), None)


# ---- "fix first" coaching -------------------------------------------------------------------

ADVICE_STEP = 15  # percentage points: one realistic coaching step for a single session
MIN_SAVING = 0.5  # seconds per 100 m below which a change is not worth suggesting first

# Technique levers at the same stroke rate: setting, direction, title, and coaching cue.
SETTING_ADVICE: tuple[tuple[str, int, str, str], ...] = (
    ('catch', 1, 'Set the catch earlier', 'Tip the fingertips down and set the forearm before you pull.'),
    ('slip', -1, 'Hold the water', 'Move the hand only as fast as it can grip, then accelerate into the push.'),
    ('drive', 1, 'Connect the hips', 'Start each pull with the hip turn, not the arm alone.'),
)


@dataclass(frozen=True, slots=True)
class Advice:
    """One change at the same stroke rate and its estimated time saving per 100 m."""

    title: str
    cue: str
    seconds_per_100: float = 0.0  # estimated saving, positive
    settings: tuple[tuple[str, int], ...] = ()  # setting changes as (field, new value)
    fault: str | None = None  # stroke fault to clear

    def apply(self, view: ViewState) -> ViewState:
        """The view with this change made; every other setting and fault is kept."""
        faults = view.faults - {self.fault} if self.fault else view.faults
        return replace(view, settings=view.settings.with_values(**dict(self.settings)), faults=frozenset(faults))


def advice(view: ViewState, limit: int = 3) -> tuple[Advice, ...]:
    """The single changes that save the most estimated time, biggest first.

    Every suggestion keeps the stroke rate: rate is a pacing choice (sprint or
    distance), so the coach only ranks technique. Each active fault, one step of
    catch, slip, or drive, and an over-long glide are scored through the same
    estimate as the header, and only savings of at least ``MIN_SAVING`` count.
    """
    active = [(key, fault) for key, fault in FAULTS.items() if key in view.faults]
    options = [Advice(f'Fix {fault.label.lower()}', fault.cue, fault=key) for key, fault in active]
    s = view.settings
    for key, direction, title, cue in SETTING_ADVICE:
        lo, hi = SETTING_RANGES[key]
        value = int(clamp(getattr(s, key) + direction * ADVICE_STEP, lo, hi))
        if value != getattr(s, key):
            options.append(Advice(title, cue, settings=((key, value),)))
    if s.glide > 50:
        cue = 'Start the catch once the arm is long; a long pause in front bleeds speed.'
        options.append(Advice('Shorten the glide', cue, settings=(('glide', 50),)))
    base = view.metrics().seconds_per_100
    scored = [replace(a, seconds_per_100=base - a.apply(view).metrics().seconds_per_100) for a in options]
    ranked = sorted((a for a in scored if a.seconds_per_100 >= MIN_SAVING), key=lambda a: -a.seconds_per_100)
    return tuple(ranked[:limit])


@dataclass(frozen=True, slots=True)
class RaceConfig:
    """One or two independent setups for a continuous swim, without starts or turns."""

    swimmers: tuple[ViewState, ...]
    distance: int = 50

    def __post_init__(self) -> None:
        if self.distance not in RACE_DISTANCES:
            raise ValueError(f'unsupported race distance {self.distance!r}')
        if not 1 <= len(self.swimmers) <= 2:
            raise ValueError('a race needs one or two swimmers')

    def finish_times(self) -> tuple[float, ...]:
        """Exact estimated finish seconds, including each swimmer's stroke faults."""
        return tuple(v.metrics().seconds_per_25 * self.distance / 25 for v in self.swimmers)

    def render_params(self) -> dict:
        """Immutable race inputs; the browser owns elapsed time, not the settings."""
        return {
            'distance': self.distance,
            'lanes': [
                {'params': v.render_params(), 'finishTime': finish}
                for v, finish in zip(self.swimmers, self.finish_times(), strict=True)
            ],
        }
