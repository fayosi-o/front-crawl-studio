"""Pure stroke model: settings, phases, timing, faults, and stroke metrics.

Everything here is UI-free so it can be unit tested.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Literal

# --- View options: each Literal is paired with the tuple the UI iterates over ---

ViewAngle = Literal['top', 'side', 'front', 'below', 'hand']
VIEW_ANGLES: tuple[ViewAngle, ...] = ('top', 'side', 'front', 'below', 'hand')
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
# catch must win back from slower water. A draggy body coasts for less time.
GLIDE_DECAY_S = 1.6  # seconds for a streamlined body's coasting speed to fall to 1/e
PROPULSIVE_S = 0.85  # seconds the hand drives the body on a mid-length underwater path

# Thrust against drag. Each stroke gives the body a push, and the water resists with a drag that
# grows with the square of speed, so at a steady pace (push per stroke × strokes per second =
# drag) speed grows only with the square root of the stroke rate: every extra stroke per minute
# buys a little less, and distance per stroke falls as the rate rises. REFERENCE_RATE is where a
# stroke's quality reads directly as metres per stroke.
REFERENCE_RATE = 42.0

# Stroke length: one curve over the whole rate range. A slower stroke has a longer underwater path
# (the hand stays in longer and finishes further back), and that longer path also carries further
# when the hand holds the water, worth up to LONG_STROKE_M extra metres at the slowest rate.
SHORT_PATH_RATE = 72.0  # spm at which the path is shortest
LONG_PATH_RATE = 22.0  # spm at which the path is longest
LONG_STROKE_M = 0.65

# A quick turnover leaves the hand less time to set the catch, so above RATE_SLIP_FROM it slips
# more, up to RATE_SLIP at the top rate. A very good catch keeps most of its hold.
RATE_SLIP_FROM = 50.0
RATE_SLIP = 0.35

# Swimmer height: longer levers cover more distance per stroke for the same effort.
REFERENCE_HEIGHT = 180  # cm

# Body roll outside this band costs drag: too flat fights the water with the shoulders and shortens
# the reach, too far wastes time and balance.
ROLL_BAND = (35, 55)  # degrees
ROLL_COST = 0.04  # distance lost at the ends of the roll range (20° and 62°)

# Kick. Still legs sink a little and drag; a kick lifts them. A six-beat kick adds some thrust,
# a two-beat kick mostly balances; either way a big kick leaves the streamline and costs effort.
KICK_THRUST = 0.05  # distance a full six-beat kick adds
KICK_DRAG = 0.02  # drag of a full-size kick
LEG_SINK = 0.025  # drag of still, sinking legs
KICK_LIFT = 0.5  # share of the Sinking legs cost a full kick wins back
SINK_REF_SPEED = 0.95  # m/s at which the legs' sinking costs its listed drag (the default stroke)
SINK_SPEED_RANGE = (0.7, 1.5)  # how far a slow or fast pace scales it
HULL_FROM = 0.95  # m/s (per sqrt of height) above which wave-making drag starts to bite: the default pace
HULL_COST = 0.6  # distance lost at 1.5x that pace is this times 0.25
HULL_MAX = 0.3
HEADLIFT_BREATH = 3  # breathing pattern at which Head lift costs its listed drag

# Head position: the head's angle from the line of the spine (0° looks straight down at the floor,
# positive looks forward). Inside HEAD_BAND it costs nothing. Lifted further, the hips and legs sink
# (more so at pace, like Sinking legs); tucked chin to chest, the head buries and drives the front
# end down. The costs are the distance lost at each end of the slider's range.
HEAD_BAND = (0, 15)  # degrees
HEAD_HIGH_COST = 0.10
HEAD_LOW_COST = 0.05

# Back arch: how far the chest leans up and out from the hips, in degrees. A little is natural and free
# (ARCH_BAND); a hollow back sinks the legs and drags, more so at pace. The cost is the distance lost at
# the top of the slider's range.
ARCH_BAND = (0, 8)  # degrees
ARCH_COST = 0.08

# Effort: the work rate of a stroke against an all-out sprint (EFFORT_SPRINT). Pushing the drag
# takes power that grows with the cube of speed, a slipping hand wastes some of it moving water,
# swinging the arms over faster costs more, and a big, frequent kick is expensive for its thrust.
TURNOVER_POWER = 0.4
KICK_POWER = 0.6


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


# With the Early exit fault the hand leaves at the waist: it keeps only this share of the finish.
EARLY_EXIT_KEEP = 0.25


def path_length(stroke_rate: float) -> float:
    """Underwater path length: 1.0 at the slowest rate (long path), 0.0 at the fastest (compact).

    The one stroke-length curve: it sets where the hand leaves the water (``exit_phase``) and how
    much extra distance a long stroke carries in the estimates.
    """
    return clamp((SHORT_PATH_RATE - stroke_rate) / (SHORT_PATH_RATE - LONG_PATH_RATE), 0.0, 1.0)


def exit_phase(length: float, early: bool = False) -> float:
    """Phase where the hand leaves the water; longer strokes stay in longer.

    ``early`` (the Early exit fault) lifts the hand out at the waist, soon after the finish starts.
    """
    exit = 0.70 + 0.08 * clamp(length, 0.0, 1.0)
    return FINISH_START + EARLY_EXIT_KEEP * (exit - FINISH_START) if early else exit


def phase_boundaries(length: float, early: bool = False) -> tuple[float, ...]:
    """Start of catch, pull, push, finish, and recovery for a given path length."""
    return CATCH_START, PULL_START, PUSH_START, FINISH_START, exit_phase(length, early)


def drive_seconds(length: float, early: bool = False, rushed: bool = False) -> float:
    """Seconds the hand drives the body in each stroke, from the start of the pull to the exit.

    A hand's drive takes about the same time at any rate, so this is ``PROPULSIVE_S`` scaled by the
    length of the driving path against a mid-length one: a longer path drives for longer, an early
    exit cuts it short, and spinning arms hurry through it.
    """
    path = exit_phase(length, early) - PULL_START
    return PROPULSIVE_S * path / (exit_phase(0.5) - PULL_START) * (RUSH if rushed else 1.0)


# Felt load. The water the hand pushes back pushes back on the palm and forearm, so through the
# pull the arm feels heavier, as if it were lifting a weight. Only the sensation grows (buoyancy
# and the estimates are unchanged), but the arm moves to it: the hand works more slowly through
# the heaviest water, speeds up out of the back as the load lets go, and the weightless recovery
# makes up the rest of the time, so the stroke rate holds. A slipping hand feels light and goes
# through almost unslowed.
LOAD_DWELL = 0.36  # extra time per unit of underwater path at full load with a full hold
LOAD_RELEASE = 0.75  # share of that time won back by the end of the push, as the load lets go


# Hand paddles: the paddled hand's area against a bare hand, and the extra arm work each pull costs.
PADDLE_AREA = 1.45
PADDLE_EFFORT = 0.1


def hand_area(faults: frozenset[str]) -> float:
    """The hand's pulling area against a bare hand: larger with hand paddles on."""
    return PADDLE_AREA if 'paddles' in faults else 1.0


def felt_load(hold_quality: float, drive_balance: float, area: float = 1.0) -> float:
    """Peak load (0–1) felt on the hand and forearm: the hold, connected to the body by the hips.

    Uses the same hold and hip connection as the estimates, so a stroke that holds water in the
    estimates also feels heavy in the arm. A larger hand (``area``, hand paddles) catches more water
    and feels heavier still.
    """
    load = clamp(hold_quality, 0.0, 1.0) * (0.7 + 0.3 * clamp(drive_balance, 0.0, 1.0))
    return clamp(load * area, 0.0, 1.0)


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


def glide_seconds(stroke_rate: float, glide: int = 50, drive: float = PROPULSIVE_S) -> float:
    """Unpropelled coast in each stroke: the time between one push ending and the next catch.

    ``drive`` is the seconds the hand drives the body (see ``drive_seconds``).
    """
    delay = stroke_time(CATCH_START, glide) - CATCH_START
    return max(0.0, 60.0 / stroke_rate - drive + delay * cycle_duration(stroke_rate))


def momentum_carry(stroke_rate: float, glide: int = 50, drive: float = PROPULSIVE_S, drag: float = 0.0) -> float:
    """Fraction of peak speed still carried when the next stroke catches (0–1).

    A low turnover leaves a long coast, so the next hand meets slower water
    and spends part of its pull re-accelerating the body. A higher turnover
    keeps the body and the water around it moving between strokes. A draggy
    body (``drag``, the fraction of distance its drag costs) slows faster in
    the coast: drag that costs a fraction d of the distance is (1 - d)^-2 times
    the streamlined drag, so the coast's time constant shrinks by (1 - d)^2.
    """
    if stroke_rate <= 0:
        raise ValueError('stroke_rate must be positive')
    decay = GLIDE_DECAY_S * (1.0 - clamp(drag, 0.0, 0.9)) ** 2
    return math.exp(-glide_seconds(stroke_rate, glide, drive) / decay)


def rate_slip(stroke_rate: float, catch_quality: float) -> float:
    """Slip (0–1) added by a quick turnover: nothing up to RATE_SLIP_FROM, then growing to the top
    rate. A hand that sets its catch well keeps most of its hold."""
    x = clamp((stroke_rate - RATE_SLIP_FROM) / (SHORT_PATH_RATE - RATE_SLIP_FROM), 0.0, 1.0)
    return RATE_SLIP * x * x * clamp(1.15 - catch_quality, 0.0, 1.0)


def pull_shape(width: int, depth: int) -> float:
    """Share (0–1) of the hold that the pull's shape keeps; ``width`` and ``depth`` in percent.

    The high-elbow "power diamond" under the body holds best. A hand wide of the shoulder sweeps
    sideways, a deep straight arm presses down before it pushes back, and the extremes (a hand
    crossing far under the body, or one held tight against it) lose a little too.
    """
    w, d = width / 100, depth / 100
    wide = max(0.0, (w - 0.5) / 0.5) ** 2
    narrow = max(0.0, (0.15 - w) / 0.15) ** 2
    deep = max(0.0, (d - 0.7) / 0.3) ** 2
    shallow = max(0.0, (0.3 - d) / 0.3) ** 2
    return 1.0 - 0.14 * wide - 0.05 * narrow - 0.10 * deep - 0.06 * shallow


def roll_drag(roll: float) -> float:
    """Fraction of distance lost to body roll outside ``ROLL_BAND``; none inside it."""
    lo, hi = ROLL_BAND
    roll_lo, roll_hi = SETTING_RANGES['roll']
    if roll < lo:
        return ROLL_COST * ((lo - roll) / (lo - roll_lo)) ** 2
    if roll > hi:
        return ROLL_COST * ((roll - hi) / (roll_hi - hi)) ** 2
    return 0.0


def arch_drag(arch: float, sink: float = 1.0) -> float:
    """Fraction of distance lost to a back arched beyond ``ARCH_BAND``; none inside it."""
    hi = ARCH_BAND[1]
    if arch <= hi:
        return 0.0
    return ARCH_COST * sink * ((arch - hi) / (SETTING_RANGES['arch'][1] - hi)) ** 2


def head_drag(head: float, sink: float = 1.0) -> float:
    """Fraction of distance lost to the head's position outside ``HEAD_BAND``; none inside it.

    ``sink`` scales the lifted head's cost with pace, as the sinking legs drag harder at speed.
    """
    lo, hi = HEAD_BAND
    head_lo, head_hi = SETTING_RANGES['head']
    if head > hi:
        return HEAD_HIGH_COST * sink * ((head - hi) / (head_hi - hi)) ** 2
    if head < lo:
        return HEAD_LOW_COST * ((lo - head) / (lo - head_lo)) ** 2
    return 0.0


def kick_thrust(kick: float, beats: int, knee_kick: bool = False) -> float:
    """Fraction of distance the kick adds; ``kick`` is the amplitude (0–1).

    A six-beat kick drives; a two-beat kick mostly times the roll and keeps a quarter of that
    thrust. Kicking from the knees wastes most of it.
    """
    share = 0.25 + 0.75 * (beats - 2) / 4
    return KICK_THRUST * clamp(kick, 0.0, 1.0) * share * (0.3 if knee_kick else 1.0)


def sink_scale(speed: float) -> float:
    """How much heavier sinking legs drag at this pace: water resistance grows with speed squared."""
    return clamp((speed / SINK_REF_SPEED) ** 2, *SINK_SPEED_RANGE)


def speed_drag(speed: float, height: int = REFERENCE_HEIGHT) -> float:
    """Fraction of distance lost to the water the body piles up at a fast pace.

    Resistance climbs faster than speed squared once the swimmer is making waves, and sooner for a
    shorter hull, so speed is taken per sqrt of height (the Froude number). Nothing is lost at or
    below ``HULL_FROM``, so the default stroke and slower ones keep their calibration.
    """
    over = max(0.0, speed * math.sqrt(REFERENCE_HEIGHT / height) / HULL_FROM - 1.0)
    return clamp(HULL_COST * over * over, 0.0, HULL_MAX)


def kick_drag(kick: float, sink: float = 1.0) -> float:
    """Fraction of distance lost by the legs: still legs sink (more so at pace), a big kick leaves the streamline."""
    k = clamp(kick, 0.0, 1.0)
    return 1.0 - (1.0 - LEG_SINK * sink * (1.0 - k) ** 2) * (1.0 - KICK_DRAG * k * k)


def work_rate(
    speed: float, hold_quality: float, stroke_rate: float, kick: float, beats: int, arm_load: float = 1.0
) -> float:
    """Power a stroke puts in, in arbitrary units (see ``EFFORT_SPRINT`` for the scale).

    ``speed`` is the pace the stroke's own push would make in a streamlined body, relative to the
    swimmer's height (m/s per 180 cm): a draggy body slows the swimmer without making the stroke
    any easier, and a taller swimmer is not charged for a longer stroke. ``arm_load`` scales the
    arms' work (hand paddles make every pull heavier).
    """
    arms = arm_load * speed**3 / (0.3 + 0.4 * clamp(hold_quality, 0.0, 1.0))  # a slipping hand wastes some
    turnover = TURNOVER_POWER * (stroke_rate / 60.0) ** 3
    legs = KICK_POWER * clamp(kick, 0.0, 1.0) ** 2 * beats / 6
    return arms + turnover + legs


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
    effort: float = 0.0  # 0–1: work rate against an all-out sprint (see work_rate)

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


@dataclass(frozen=True, slots=True)
class Fault:
    """A common stroke error that can be switched on to show its shape and cost.

    The same switch also carries a few good-form cues (``good``) that fix an error, such as Wrist press.
    """

    label: str
    hint: str  # what the fault looks like
    cue: str  # coaching cue that fixes it
    drag: float = 0.0  # fraction of distance per stroke lost to body drag (also shortens the coast)
    slip: float = 0.0  # added to slip (0–1)
    catch: float = 0.0  # removed from catch quality (0–1)
    push: float = 0.0  # fraction of each stroke's push lost
    reach: float = 0.0  # fraction of distance per stroke gained (good form only)
    good: bool = False  # good form to switch on, not an error: its gains are negative catch and slip costs
    kit: bool = False  # training equipment (hand paddles), listed under Equipment; always also ``good``


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
    'samesidekick': Fault(
        'Same-side kick',
        "The downbeat lands with the same-side hand's catch instead of the opposite one, so the diagonal link "
        'from shoulder to opposite hip never loads: the hips sway and the legs have to correct.',
        'Kick down with the opposite leg as each hand catches: right hand, left foot.',
        catch=0.05,
        drag=0.04,
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
        'The head lifts forward to breathe, so the chest rises, the hips drop and each breath stalls the stroke. '
        'The more often you breathe, the more it costs.',
        'Turn to breathe with one goggle in the water; the roll makes the room.',
        drag=0.06,  # at a breath every HEADLIFT_BREATH strokes
    ),
    'earlyexit': Fault(
        'Early exit',
        'The hand lifts out at the waist, cutting off the end of the push, its fastest part.',
        'Push all the way past the hip; brush the thigh with the thumb before you lift.',
        push=0.07,
    ),
    'droppedelbow': Fault(
        'Dropped elbow',
        'The elbow sinks below the hand at the catch, so the palm presses down and slides instead of pushing back.',
        'Keep the elbow near the surface and tip the hand and forearm down beneath it.',
        catch=0.30,
        slip=0.08,
    ),
    'lopsided': Fault(
        'Lopsided pull',
        'The right arm catches late and presses down while the left holds, so the pull is uneven '
        'and the body yaws off line.',
        'Match the right catch to the left; practise one-arm drill on the weaker side.',
        catch=0.12,
        drag=0.03,
    ),
    'earlyroll': Fault(
        'Early rotation',
        'The body rolls to the next side while the hand is still pulling, with the shoulders turning ahead of '
        'the hips, so the catch has nothing solid to push against and the torso twists.',
        'Hold the roll until the catch is set: pull with the body still, then let the hips turn the stroke over.',
        catch=0.18,
        slip=0.06,
        drag=0.02,
    ),
    'wristpress': Fault(
        'Wrist press',
        'The wrist flexes back through the catch so the palm and forearm press straight back, with the elbow '
        'held high and the hand never pressing down.',
        'Press with the wrist: cock the hand back so the palm faces the wall behind you, not the floor.',
        catch=-0.05,
        slip=-0.03,
        good=True,
    ),
    'shoulderreach': Fault(
        'Shoulder reach',
        'The shoulder rolls forward as the hand enters, so the arm reaches longer in front before the catch.',
        'Extend the shoulder: reach through from the shoulder, not just the arm, before you start the catch.',
        reach=0.03,
        good=True,
    ),
    'hipfinish': Fault(
        'Hip finish & roll',
        'The hand pushes the water all the way back to the hip, and the hips and shoulders roll together '
        'as the push ends, turning about a still head like a corkscrew.',
        'Push water to the hip, then rotate: keep the head still and turn the body as one unit.',
        push=-0.03,
        good=True,
    ),
    'pushdown': Fault(
        'Pressing down',
        'The hand presses down toward the floor through the push instead of driving back, so the water is '
        'squeezed under the body and the stroke loses its power.',
        'Push back along the body, not down: keep the palm facing the wall behind you.',
        push=0.06,
        slip=0.04,
    ),
    'flatpush': Fault(
        'Parallel push',
        'The hand drives straight back level with the body, staying deep and pushing water directly behind you, '
        'and only comes up as the push ends.',
        'Push parallel to the line of your body: palm to the wall behind, hand level until the hip.',
        push=-0.03,
        good=True,
    ),
    'upsweep': Fault(
        'Late upsweep',
        'At the last moment the hand sweeps up toward the surface, keeping pressure on the water to the very end '
        'and leaving the water moving.',
        'Finish the push with an upward flick past the hip, then let the hand slip out.',
        push=-0.02,
        good=True,
    ),
    'paddles': Fault(
        'Hand paddles',
        'Medium hand paddles strapped to each palm: the hand holds more water, so each stroke carries further '
        'and the arm feels heavier, but every pull costs more effort and loads the shoulder.',
        'Keep the catch patient and the elbow high, and build up slowly: paddles load the shoulder.',
        slip=-0.04,
        push=-0.05,
        good=True,
        kit=True,
    ),
}
# The right arm's catch with the Lopsided pull fault, as a share of the left arm's (engine.js).
LOPSIDED_CATCH = 0.55

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


def fault_drag(faults: frozenset[str], settings: StrokeSettings | None = None, sink: float = 1.0) -> float:
    """Combined fractional distance loss from drag-type faults.

    Head lift costs more the more often the swimmer breathes, and a strong kick wins back part
    of the Sinking legs cost by lifting the legs. ``sink`` scales the Sinking legs cost with pace
    (see ``sink_scale``).
    """
    s = settings or StrokeSettings()
    keep = 1.0
    for key in faults:
        drag = FAULTS[key].drag
        if key == 'headlift':
            drag *= HEADLIFT_BREATH / s.breath
        elif key == 'sinking':
            drag *= sink * (1.0 - KICK_LIFT * s.kick / 100)
        keep *= 1.0 - drag
    return 1.0 - keep


def body_drag(settings: StrokeSettings, faults: frozenset[str] = frozenset(), speed: float = SINK_REF_SPEED) -> float:
    """Fraction of distance lost to the body's drag: faults, roll, the head, the legs and, at a fast pace, waves."""
    sink = sink_scale(speed)
    parts = (
        fault_drag(faults, settings, sink),
        roll_drag(settings.roll),
        head_drag(settings.head, sink),
        arch_drag(settings.arch, sink),
        kick_drag(settings.kick / 100, sink),
        speed_drag(speed, settings.height),
    )
    return 1.0 - math.prod(1.0 - part for part in parts)


def timeline_boundaries(
    length: float, rushed: bool = False, glide: int = 50, feel: float = 0.0, early: bool = False
) -> tuple[float, ...]:
    """Phase boundaries as seen on screen.

    A heavy felt load (``feel``) slows the hand under water and shortens the recovery; a rushed
    stroke squeezes the underwater part; an early exit (``early``) cuts the finish short.
    """
    bounds = phase_boundaries(length, early)
    exit = bounds[-1]
    rush = RUSH if rushed else 1.0
    return tuple(stroke_time(loaded_time(b, exit, feel, rush), glide) for b in bounds)


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
    'head': (-20, 40),
    'arch': (0, 30),
    'slip': (0, 100),
    'width': (0, 100),
    'depth': (0, 100),
    'entry': (0, 40),
    'drive': (0, 100),
    'kick': (0, 100),
    'beats': (2, 6),
    'glide': (0, 100),
    'breath': (2, 5),
    'height': (150, 200),
}
# Settings that move in coarser steps than 1 (kicks per arm cycle: 2, 4, or 6).
SETTING_STEPS: dict[str, int] = {'beats': 2}


@dataclass(frozen=True, slots=True)
class StrokeSettings:
    """User-facing settings: percentages 0–100, rate in spm, roll, head and entry in degrees, height in cm."""

    rate: int = 42
    catch: int = 92
    roll: int = 46
    head: int = 5  # head angle from the spine line in degrees: 0 = eyes on the floor, + looks forward
    arch: int = 0  # back arch in degrees: the chest leaning up and out from the hips
    slip: int = 8
    width: int = 35  # pull width: 0 = hand sweeps in under the body, 100 = wide of the shoulder line
    depth: int = 50  # pull depth: 0 = hand close to the body, 100 = deep, straighter arm
    entry: int = 5
    drive: int = 85
    kick: int = 45
    beats: int = 2  # kicks per arm cycle; the two-beat kick times the hip rotation
    glide: int = 50  # front-end timing: 0 = earlier catch, 50 = normal, 100 = longer glide
    breath: int = 3  # hand entries per breath: odd counts alternate sides, even counts breathe right
    height: int = REFERENCE_HEIGHT  # the swimmer's height in cm; scales the stroke's length

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
        return estimate_metrics(self)


def effective_hold(settings: StrokeSettings, faults: frozenset[str] = frozenset()) -> tuple[float, float]:
    """Catch quality and slip as fractions after hold-type faults and a quick turnover."""
    catch = clamp(settings.catch / 100 - sum(FAULTS[k].catch for k in faults), 0.0, 1.0)
    slip = settings.slip / 100 + sum(FAULTS[k].slip for k in faults) + rate_slip(settings.rate, catch)
    return catch, clamp(slip, 0.0, 1.0)


def _stroke(settings: StrokeSettings, faults: frozenset[str]) -> tuple[float, float, float, float]:
    """Hold quality, distance per stroke, momentum carry and work rate (see ``estimate_metrics``)."""
    s = settings
    catch, slip = effective_hold(s, faults)
    hold = clamp(0.6 * catch + 0.4 * (1.0 - slip), 0.0, 1.0) * pull_shape(s.width, s.depth)
    # Drive multiplies the hold rather than adding to it.
    connection = 0.7 + 0.3 * s.drive / 100
    length = path_length(s.rate)
    # Metres per stroke at REFERENCE_RATE: a long path carries further only when the hand holds.
    quality = 0.60 + 0.75 * hold * connection - 0.32 * slip + LONG_STROKE_M * length**2 * hold
    kick = kick_thrust(s.kick / 100, s.beats, 'kneekick' in faults)
    push = math.prod(1.0 - FAULTS[k].push for k in faults)
    reach = 1.0 + sum(FAULTS[k].reach for k in faults)
    # The pace before the body's drag sets how hard the legs' sinking drags.
    pace = quality * math.sqrt(REFERENCE_RATE / s.rate) * (1.0 + kick) * push * s.height / REFERENCE_HEIGHT
    drag = body_drag(s, faults, pace * s.rate / 60.0)
    drive = drive_seconds(length, 'earlyexit' in faults, 'rushing' in faults)
    momentum = momentum_carry(s.rate, s.glide, drive, drag)
    distance_per_stroke = clamp(
        quality
        * math.sqrt(REFERENCE_RATE / s.rate)  # thrust against drag: see REFERENCE_RATE
        * (0.80 + 0.20 * momentum)
        * (1.0 + kick)
        * push
        * reach
        * (1.0 - drag)
        * s.height
        / REFERENCE_HEIGHT,
        0.40,
        2.60,
    )
    speed = distance_per_stroke * s.rate / 60.0
    streamlined = speed / (1.0 - drag) * REFERENCE_HEIGHT / s.height
    arm_load = 1.0 + PADDLE_EFFORT * ('paddles' in faults)
    power = work_rate(streamlined, hold, s.rate, s.kick / 100, s.beats, arm_load)
    return hold, distance_per_stroke, momentum, power


# The all-out sprint that sets the effort scale: top rate, full six-beat kick, default technique.
EFFORT_SPRINT = StrokeSettings(rate=72, kick=100, beats=6)


@functools.cache
def _sprint_power() -> float:
    return _stroke(EFFORT_SPRINT, frozenset())[3]


def estimate_metrics(settings: StrokeSettings, faults: frozenset[str] = frozenset()) -> Metrics:
    """Estimate a stroke's efficiency and effort from its settings and active faults.

    - Hold: catch and slip, after faults and the extra slip of a quick turnover, kept or lost by
      the pull's shape. Drive multiplies the hold, so it cannot rescue a poor catch or heavy slip,
      and slip also costs distance directly.
    - Length: a slower stroke's longer underwater path carries further, only as far as the hand
      holds the water.
    - Thrust against drag: distance per stroke falls with the square root of the rate, so a higher
      rate is faster but each extra stroke buys less.
    - Momentum: low rates, longer glides and a draggy body lose speed between strokes.
    - Drag: faults, roll or head outside its band, still legs and a big kick each cost a fraction; a kick
      adds a little thrust; an early exit loses part of each push. Height scales the stroke.
    - Effort: the work rate against an all-out sprint (``EFFORT_SPRINT``), capped at 1.
    """
    hold, distance_per_stroke, momentum, power = _stroke(settings, faults)
    strokes_per_25 = 25.0 / distance_per_stroke
    return Metrics(
        hold_quality=hold,
        distance_per_stroke=distance_per_stroke,
        strokes_per_25=strokes_per_25,
        seconds_per_25=strokes_per_25 * 60.0 / settings.rate,
        momentum=momentum,
        effort=clamp(power / _sprint_power(), 0.0, 1.0),
    )


@dataclass(frozen=True, slots=True)
class ViewState:
    """Everything one browser tab shows: stroke settings plus view options.

    Immutable; the app replaces it on every change, and the constructor
    validates every field.
    """

    settings: StrokeSettings = field(default_factory=StrokeSettings)
    playing: bool = True
    playback: float = 1.0
    faults: frozenset[str] = frozenset()
    split: bool = False
    angle: ViewAngle = 'top'
    trail: Trail = 'off'
    trail_seconds: float = 1.5
    pressure: bool = False
    flow: bool = False
    chain: bool = False
    anchor: bool = False
    catch_focus: bool = False
    drill: DrillName = 'off'

    def __post_init__(self) -> None:
        for name in ('playing', 'split', 'pressure', 'flow', 'chain', 'anchor', 'catch_focus'):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f'{name} must be true or false')
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
        """Catch quality and slip as fractions after hold-type faults and a quick turnover."""
        return effective_hold(self.settings, self.faults)

    def exit_phase(self) -> float:
        """Phase where the hand leaves the water, after the Early exit fault."""
        return exit_phase(path_length(self.settings.rate), 'earlyexit' in self.faults)

    def metrics(self) -> Metrics:
        """Estimates for the settings with every active fault applied."""
        return estimate_metrics(self.settings, self.faults)

    def render_params(self, metrics: Metrics | None = None) -> dict[str, int | float | str | bool | list[str]]:
        """Parameters for the browser animation loop (fractions, not percentages)."""
        s = self.settings
        m = metrics if metrics is not None else self.metrics()
        length = path_length(s.rate)
        catch, slip = self.effective_hold()
        drive = drive_seconds(length, 'earlyexit' in self.faults, 'rushing' in self.faults)
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
            'head': s.head,
            'arch': s.arch,
            'playing': self.playing,
            'playback': self.playback,
            'length': length,
            'exit': self.exit_phase(),
            'scale': s.height / REFERENCE_HEIGHT,  # the swimmer's size against the 180 cm model
            'faults': sorted(self.faults),
            'rush': RUSH if 'rushing' in self.faults else 1.0,
            'feel': felt_load(m.hold_quality, s.drive / 100, hand_area(self.faults)),
            'trail': self.trail,
            'trailSeconds': self.trail_seconds,
            'pressure': self.pressure,
            'flow': self.flow,
            'chain': self.chain,
            'anchor': self.anchor,
            'catchFocus': self.catch_focus,
            'speed': speed,  # metres per second, averaged over the cycle
            'momentum': m.momentum,
            # Share of each stroke spent coasting; the engine shapes the speed surge from it.
            'glide': glide_seconds(s.rate, s.glide, drive) * s.rate / 60.0,
            'rideHeight': ride_height,
            'hipDrop': hip_drop,
        }


# Example strokes, ordered from most to least efficient by SWOLF (strokes plus seconds per 25 m,
# lower first; keys 1–4 in the UI). The first three are distance strokes built on a two- or
# four-beat kick. Presets set the stroke, not the swimmer: they keep the swimmer's height.
PRESETS: dict[str, StrokeSettings] = {
    # The same form at a distance pace: slower turnover, a longer glide and a lighter four-beat kick.
    'Phelps relaxed': StrokeSettings(
        rate=36, catch=95, roll=52, slip=6, width=25, depth=55, entry=8, drive=85, kick=50, beats=4, glide=55
    ),
    # From underwater stills of Phelps: full reach, high-elbow catch under the body, a long push past the
    # hip, big shoulder-and-hip roll and a steady six-beat kick.
    'Phelps-style': StrokeSettings(
        rate=50, catch=95, roll=54, slip=6, width=25, depth=55, entry=8, drive=90, kick=70, beats=6, glide=40
    ),
    'Long power': StrokeSettings(rate=42, catch=92, roll=46, slip=8, width=35, drive=85, kick=45, beats=2),
    'Long light': StrokeSettings(rate=44, catch=88, roll=44, slip=10, width=40, drive=70, kick=30, beats=2),
    'Compact connected': StrokeSettings(rate=52, catch=82, roll=40, slip=14, width=30, drive=68, kick=55, beats=4),
    'Short slipping': StrokeSettings(rate=56, catch=42, roll=34, slip=62, width=85, drive=35, kick=40, beats=6),
}


def preset_for(name: str, settings: StrokeSettings) -> StrokeSettings:
    """Preset ``name`` for the swimmer in ``settings``: the preset's stroke at their height."""
    return PRESETS[name].with_values(height=settings.height)


def matching_preset(settings: StrokeSettings) -> str | None:
    """Name of the preset whose stroke these settings equal (at any height), or None if custom."""
    return next((name for name in PRESETS if preset_for(name, settings) == settings), None)


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
    catch, slip, or drive, an over-long glide and a head outside its neutral band
    are scored through the same
    estimate as the header, and only savings of at least ``MIN_SAVING`` count.
    """
    active = [(key, fault) for key, fault in FAULTS.items() if key in view.faults and not fault.good]
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
    level = int(clamp(s.head, *HEAD_BAND))
    if level != s.head:
        cue = (
            'Look at the floor just ahead of you; let the waterline cross the crown of your head.'
            if s.head > level
            else 'Lift the chin off your chest and look at the floor below, not back at your hips.'
        )
        options.append(Advice('Level the head', cue, settings=(('head', level),)))
    if s.arch > ARCH_BAND[1]:
        cue = 'Keep the ribs down and the belly lightly braced so the lower back stays long, not hollow.'
        options.append(Advice('Ease the back arch', cue, settings=(('arch', ARCH_BAND[1]),)))
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
