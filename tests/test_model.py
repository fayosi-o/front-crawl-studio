"""Unit tests for the pure stroke model: timing, phases, estimates, faults, and validation."""

import math
from dataclasses import astuple
from itertools import pairwise

import pytest

from long_catch.model import (
    ADVICE_STEP,
    CATCH_START,
    DRILLS,
    EFFORT_SPRINT,
    FAULTS,
    FINISH_START,
    HULL_FROM,
    LOAD_DWELL,
    LOAD_RELEASE,
    MIN_SAVING,
    PADDLE_AREA,
    PRESETS,
    PROPULSIVE_S,
    RUSH,
    Advice,
    Metrics,
    Phase,
    RaceConfig,
    StrokeSettings,
    ViewState,
    advice,
    arch_drag,
    arm_phases,
    cycle_duration,
    drive_seconds,
    estimate_metrics,
    exit_phase,
    felt_load,
    format_duration,
    head_drag,
    load_profile,
    loaded_time,
    matching_preset,
    momentum_carry,
    path_length,
    phase_boundaries,
    phase_to_step,
    preset_for,
    pull_shape,
    rate_slip,
    roll_drag,
    sink_scale,
    speed_drag,
    stroke_phase,
    stroke_time,
    timeline_boundaries,
    waterline_pose,
)


def est(catch: float = 0.92, slip: float = 0.08, drive: float = 0.85, rate: int = 42, **other: int) -> Metrics:
    """Estimates for fractional catch, slip and drive at ``rate`` (other settings as given or default)."""
    settings = StrokeSettings(catch=round(catch * 100), slip=round(slip * 100), drive=round(drive * 100), rate=rate)
    return estimate_metrics(settings.with_values(**other))


def test_cycle_duration_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        cycle_duration(0)


def test_arms_wrap_and_stay_half_a_cycle_apart():
    assert arm_phases(1.25) == pytest.approx((0.25, 0.75))


@pytest.mark.parametrize(
    ('phase', 'expected'),
    [
        (0.1199, Phase.ENTRY),
        (0.12, Phase.CATCH),
        (0.30, Phase.PULL),
        (0.7401, Phase.RECOVERY),
    ],
)
def test_phase_to_step_boundaries(phase, expected):
    assert phase_to_step(phase, length=0.5) == expected


def test_longer_stroke_stays_underwater_longer():
    assert exit_phase(1.0) > exit_phase(0.0)
    assert phase_to_step(0.76, length=1.0) == Phase.FINISH
    assert phase_to_step(0.76, length=0.0) == Phase.RECOVERY


def test_push_is_distinct_from_pull_and_finish_without_extending_the_cycle():
    assert phase_to_step(0.49).label == 'Pull'
    assert phase_to_step(0.50).label == 'Push'
    assert phase_to_step(0.6599).label == 'Push'
    assert phase_to_step(0.66).label == 'Finish'
    assert timeline_boundaries(0.5) == pytest.approx((0.12, 0.30, 0.50, 0.66, 0.74))
    assert cycle_duration(40) == 3.0


def test_path_length_is_one_curve_over_the_whole_rate_range():
    assert path_length(22) == 1.0
    assert path_length(72) == 0.0
    lengths = [path_length(rate) for rate in range(22, 73)]
    assert lengths == sorted(lengths, reverse=True) and len(set(lengths)) == len(lengths)
    params = ViewState(settings=StrokeSettings(rate=30)).render_params()
    assert params['length'] == path_length(30) and params['exit'] == exit_phase(path_length(30))


def test_format_duration_carries_rounded_seconds_into_the_next_minute():
    assert format_duration(59.96) == '1:00.0'


def test_more_slip_reduces_distance_per_stroke():
    for rate in (22, 42, 72):
        assert est(0.9, 0.7, 0.7, rate).distance_per_stroke < est(0.9, 0.1, 0.7, rate).distance_per_stroke


def test_better_catch_improves_distance_per_stroke():
    assert est(0.9, 0.1, 0.7, 40).distance_per_stroke > est(0.3, 0.1, 0.7, 40).distance_per_stroke


def test_drive_cannot_rescue_poor_catch_and_slip():
    for rate in (22, 42, 72):
        assert est(0.3, 0.7, 1.0, rate).distance_per_stroke < est(0.9, 0.1, 0.0, rate).distance_per_stroke


def test_low_rate_loses_momentum_and_distance_in_the_glide():
    slow, quick = est(0.9, 0.1, 0.7, 30), est(0.9, 0.1, 0.7, 50)
    assert 0 < slow.momentum < quick.momentum <= 1
    assert slow.seconds_per_25 > est(0.9, 0.1, 0.7, 42).seconds_per_25
    assert momentum_carry(200) == 1.0
    carries = [StrokeSettings(rate=rate).metrics().momentum for rate in range(22, 73)]
    assert carries == sorted(carries)


def test_slow_long_stroke_reaches_further_only_when_holding_water():
    m = StrokeSettings(rate=22).metrics()
    assert m.distance_per_stroke == pytest.approx(2.17, abs=0.02)
    assert m.strokes_per_25 == pytest.approx(11.5, abs=0.2)
    assert m.seconds_per_100 == pytest.approx(126, abs=2)
    gain = m.distance_per_stroke - StrokeSettings().metrics().distance_per_stroke
    slipping_gain = est(0.3, 0.7, 1.0, 22).distance_per_stroke - est(0.3, 0.7, 1.0, 42).distance_per_stroke
    assert 0 < slipping_gain < 0.6 * gain  # a slipping hand gains much less from the long stroke


def test_thrust_against_drag_gives_diminishing_returns_for_rate():
    speeds = [StrokeSettings(rate=rate).metrics().speed for rate in range(22, 73)]
    gains = [b - a for a, b in pairwise(speeds)]
    assert all(gain > 0 for gain in gains)  # a good stroke still goes faster at a higher rate,
    assert sum(gains[20:]) / 30 < 0.6 * sum(gains[:20]) / 20  # but each stroke above 42 spm buys less,
    assert all(abs(later - earlier) < 0.08 * earlier for earlier, later in pairwise(gains))  # with no dip or jump
    distances = [StrokeSettings(rate=rate).metrics().distance_per_stroke for rate in range(22, 73)]
    assert distances == sorted(distances, reverse=True)
    # Rate is not free: the work rate climbs steeply towards the top rate.
    efforts = [StrokeSettings(rate=rate).metrics().effort for rate in (22, 42, 56, 72)]
    assert efforts == sorted(efforts) and efforts[-1] - efforts[-2] > efforts[1] - efforts[0]


def test_a_quick_turnover_slips_a_poor_catch_so_its_best_rate_is_lower():
    assert rate_slip(50, 0.5) == 0 == rate_slip(30, 0.0)
    assert rate_slip(72, 0.5) > rate_slip(72, 0.95) > rate_slip(60, 0.95) > 0
    poor = [StrokeSettings(rate=rate, catch=50, slip=30).metrics().speed for rate in range(22, 73)]
    best = 22 + poor.index(max(poor))
    assert 50 < best < 72
    fast = ViewState(settings=StrokeSettings(rate=72, catch=50)).render_params()
    assert fast['slip'] > ViewState(settings=StrokeSettings(rate=50, catch=50)).render_params()['slip']


def test_drive_time_follows_the_underwater_path():
    assert drive_seconds(0.5) == pytest.approx(PROPULSIVE_S)
    assert drive_seconds(1.0) > drive_seconds(0.5) > drive_seconds(0.0)
    assert drive_seconds(0.5, early=True) < drive_seconds(0.5)
    assert drive_seconds(0.5, rushed=True) == pytest.approx(RUSH * PROPULSIVE_S)
    # A shorter drive leaves a longer coast at the same rate.
    assert momentum_carry(42, drive=drive_seconds(0.5, early=True)) < momentum_carry(42, drive=drive_seconds(0.5))


def test_a_draggy_body_loses_more_speed_in_the_glide():
    assert momentum_carry(42, drag=0.2) < momentum_carry(42, drag=0.05) < momentum_carry(42)
    clean = ViewState()
    for key in ('sinking', 'snaking', 'crossover'):
        assert clean.with_fault(key, True).metrics().momentum < clean.metrics().momentum
    # The penalty for a long glide grows with drag.
    long_glide = clean.settings.with_values(glide=100)

    def glide_loss(faults: frozenset[str]) -> float:
        short, long = ViewState(faults=faults), ViewState(settings=long_glide, faults=faults)
        return short.metrics().momentum - long.metrics().momentum

    assert glide_loss(frozenset({'sinking'})) > glide_loss(frozenset())


def test_effort_counts_the_stroke_not_the_drag():
    clean = StrokeSettings().metrics()
    assert 0.3 < clean.effort < 0.6
    assert EFFORT_SPRINT.metrics().effort == pytest.approx(1.0)
    assert all(0 <= v.metrics().effort <= 1 for v in (ViewState(faults=frozenset(FAULTS)), ViewState()))
    # Drag slows the swimmer without making the stroke easier; a slipping hand feels light.
    for key in ('crossover', 'sinking', 'snaking'):
        assert ViewState(faults=frozenset({key})).metrics().effort == pytest.approx(clean.effort, rel=0.05)
    assert PRESETS['Short slipping'].metrics().effort < clean.effort
    # Height does not change the work of the same stroke.
    assert StrokeSettings(height=200).metrics().effort == pytest.approx(clean.effort, rel=0.01)


@pytest.mark.parametrize('glide', [0, 50, 100])
def test_glide_timing_is_continuous_monotonic_and_keeps_cycle_length(glide):
    phases = [stroke_phase(i / 1000, glide) for i in range(1000)]
    assert phases == sorted(phases)
    assert phases[0] == 0
    assert stroke_phase(0.30, glide) == 0.30
    assert stroke_phase(1, glide) == 0
    for rushed in (False, True):
        bounds = timeline_boundaries(0.5, rushed, glide)
        expected = [b * (RUSH if rushed else 1) for b in phase_boundaries(0.5)]
        assert [stroke_phase(b, glide) for b in bounds] == pytest.approx(expected)
    for phase in (0.05, 0.12, 0.22, 0.30, 0.66, 0.99):
        assert stroke_phase(stroke_time(phase, glide), glide) == pytest.approx(phase)


def test_longer_glide_delays_catch_and_costs_momentum_at_the_same_rate():
    views = [ViewState(settings=StrokeSettings(glide=g)) for g in (0, 50, 100)]
    params = [v.render_params() for v in views]
    assert {p['rate'] for p in params} == {42}
    assert params[0]['catchDelay'] < 0 == params[1]['catchDelay'] < params[2]['catchDelay']
    assert params[0]['glide'] < params[1]['glide'] < params[2]['glide']
    assert stroke_phase(CATCH_START, 100) < CATCH_START < stroke_phase(CATCH_START, 0)
    assert views[0].metrics().momentum > views[1].metrics().momentum > views[2].metrics().momentum
    assert views[0].metrics().distance_per_stroke > views[1].metrics().distance_per_stroke
    assert views[1].metrics().distance_per_stroke > views[2].metrics().distance_per_stroke
    for view in views:
        assert view.settings.metrics() == view.metrics()
    with pytest.raises(ValueError):
        StrokeSettings(glide=101)


def test_pull_shape_keeps_the_hold_in_the_power_diamond():
    assert pull_shape(35, 50) == 1.0 == pull_shape(20, 30) == pull_shape(50, 70)
    assert pull_shape(100, 50) < pull_shape(85, 50) < 1.0  # a wide hand sweeps sideways
    assert pull_shape(35, 100) < 1.0 and pull_shape(35, 0) < 1.0 and pull_shape(0, 50) < 1.0
    base = StrokeSettings().metrics()
    for change in ({'width': 90}, {'depth': 100}):
        m = StrokeSettings(**change).metrics()
        assert m.hold_quality < base.hold_quality and m.distance_per_stroke < base.distance_per_stroke
    params = ViewState(settings=StrokeSettings(width=100), pressure=True).render_params()
    assert (params['width'], params['pressure']) == (1, True)
    assert ViewState(flow=True).render_params()['flow'] is True
    assert ViewState().render_params()['flow'] is False
    assert ViewState(chain=True).render_params()['chain'] is True
    assert ViewState(anchor=True).render_params()['anchor'] is True
    assert ViewState().render_params()['anchor'] is False
    assert ViewState(anchor_keep=True).render_params()['anchorKeep'] is True
    assert ViewState().render_params()['anchorKeep'] is False
    assert ViewState(catch_focus=True).render_params()['catchFocus'] is True
    assert ViewState().render_params()['catchFocus'] is False


def test_roll_outside_its_band_costs_drag():
    assert roll_drag(35) == roll_drag(46) == roll_drag(55) == 0.0
    assert roll_drag(20) == pytest.approx(0.04) and roll_drag(62) == pytest.approx(0.04)
    assert roll_drag(30) < roll_drag(25) and roll_drag(58) < roll_drag(60)
    base = StrokeSettings().metrics().distance_per_stroke
    assert StrokeSettings(roll=20).metrics().distance_per_stroke < base
    assert StrokeSettings(roll=62).metrics().distance_per_stroke < base
    assert StrokeSettings(roll=50).metrics().distance_per_stroke == base


def test_kick_lifts_the_legs_and_a_six_beat_kick_drives_at_a_cost():
    still, moderate = StrokeSettings(kick=0).metrics(), StrokeSettings(kick=45).metrics()
    assert still.speed < moderate.speed  # still legs sink and drag
    six = StrokeSettings(kick=100, beats=6).metrics()
    assert six.speed > moderate.speed and six.effort > moderate.effort + 0.1
    assert StrokeSettings(kick=100, beats=2).metrics().speed < moderate.speed  # a big two-beat kick only drags
    for beats in (3, 8):
        with pytest.raises(ValueError):
            StrokeSettings(beats=beats)
    assert ViewState(settings=StrokeSettings(beats=6)).render_params()['beats'] == 6


def test_a_kick_wins_back_part_of_the_sinking_legs_cost():
    def cost(kick: int) -> float:
        settings = StrokeSettings(kick=kick)
        sunk = ViewState(settings=settings, faults=frozenset({'sinking'})).metrics()
        return 1 - sunk.distance_per_stroke / settings.metrics().distance_per_stroke

    assert cost(0) > cost(45) > cost(100) > 0


def test_head_lift_costs_more_the_more_often_you_breathe():
    def cost(breath: int) -> float:
        settings = StrokeSettings(breath=breath)
        lifted = ViewState(settings=settings, faults=frozenset({'headlift'})).metrics()
        return lifted.seconds_per_100 - settings.metrics().seconds_per_100

    assert cost(2) > cost(3) > cost(4) > cost(5) > 0


def test_height_scales_the_stroke_and_the_swimmer():
    tall, short = StrokeSettings(height=200).metrics(), StrokeSettings(height=150).metrics()
    base = StrokeSettings().metrics()
    assert tall.distance_per_stroke / base.distance_per_stroke == pytest.approx(
        200 / 180, rel=0.02
    )  # a faster swimmer's legs and waves drag a touch more
    assert short.distance_per_stroke < base.distance_per_stroke < tall.distance_per_stroke
    assert ViewState(settings=StrokeSettings(height=200)).render_params()['scale'] == pytest.approx(200 / 180)
    for height in (149, 201):
        with pytest.raises(ValueError):
            StrokeSettings(height=height)


def test_presets_keep_the_swimmers_height():
    tall = StrokeSettings(height=192)
    for name in PRESETS:
        assert preset_for(name, tall).height == 192
        assert matching_preset(preset_for(name, tall)) == name
    assert matching_preset(tall) == 'Long power'


def test_presets_run_from_most_to_least_efficient_by_swolf():
    swolf = [settings.metrics().swolf for settings in PRESETS.values()]
    assert swolf == sorted(swolf) and len(set(swolf)) == len(swolf)


def test_outputs_are_finite_and_consistent():
    result = est(0.9, 0.1, 0.7, 40)
    assert all(math.isfinite(value) for value in astuple(result))
    assert result.strokes_per_25 == pytest.approx(25 / result.distance_per_stroke)
    assert result.seconds_per_25 == pytest.approx(result.strokes_per_25 * 60 / 40)
    params = ViewState().render_params()
    assert all(0 <= params[key] <= 1 for key in ('catch', 'slip', 'drive', 'kick', 'length', 'exit'))
    assert params['exit'] == exit_phase(params['length'])


def test_settings_validate_ranges():
    with pytest.raises(ValueError):
        StrokeSettings(rate=10)
    with pytest.raises(ValueError):
        StrokeSettings(slip=101)
    for kick in (-1, 101):
        with pytest.raises(ValueError):
            StrokeSettings(kick=kick)
    assert StrokeSettings().with_values(slip=20).slip == 20


def test_view_options_validate_and_trail_reaches_the_engine():
    for bad in (
        {'angle': 'behind'},
        {'trail': 'elbows'},
        {'trail_seconds': 9.0},
        {'playback': 3.0},
        {'pressure': list(range(1000))},
        {'split': 'yes'},
        {'playing': None},
    ):
        with pytest.raises(ValueError):
            ViewState(**bad)
    params = ViewState(trail='hands', trail_seconds=3.0).render_params()
    assert (params['trail'], params['trailSeconds']) == ('hands', 3.0)


def test_matching_preset_identifies_unchanged_presets_only():
    assert all(matching_preset(settings) == name for name, settings in PRESETS.items())
    assert matching_preset(PRESETS['Long power'].with_values(kick=0)) is None
    metrics = {name: s.metrics().distance_per_stroke for name, s in PRESETS.items()}
    assert len(set(PRESETS.values())) == len(PRESETS)
    assert metrics['Long power'] > metrics['Compact connected'] > metrics['Short slipping']


def test_kick_control_is_normalized_for_the_engine():
    assert ViewState(settings=StrokeSettings(kick=0)).render_params()['kick'] == 0
    assert ViewState(settings=StrokeSettings(kick=100)).render_params()['kick'] == 1


def test_entry_angle_is_visual_only_and_passed_in_degrees():
    flat = StrokeSettings(entry=0)
    steep = flat.with_values(entry=40)
    assert flat.metrics() == steep.metrics()
    assert ViewState(settings=steep).render_params()['entry'] == 40
    with pytest.raises(ValueError):
        StrokeSettings(entry=41)


def test_stroke_depth_is_normalized_and_validated():
    assert ViewState(settings=StrokeSettings(depth=100)).render_params()['depth'] == 1
    with pytest.raises(ValueError):
        StrokeSettings(depth=101)


def test_every_fault_costs_distance_and_unknown_faults_are_rejected():
    clean = ViewState().metrics().distance_per_stroke
    for key, fault in FAULTS.items():
        if not fault.good:
            assert ViewState(faults=frozenset({key})).metrics().distance_per_stroke < clean
    with pytest.raises(ValueError):
        ViewState(faults=frozenset({'flailing'}))


def test_faults_stack_and_clear():
    view = ViewState().with_fault('crossover', True).with_fault('snaking', True)
    both = view.metrics().distance_per_stroke
    assert both < ViewState(faults=frozenset({'crossover'})).metrics().distance_per_stroke
    assert view.with_fault('crossover', False).with_fault('snaking', False) == ViewState()


def test_spinning_arms_slip_and_rush_the_underwater_phase():
    view = ViewState(faults=frozenset({'rushing'}))
    assert not view.metrics().holding
    params = view.render_params()
    assert params['slip'] > ViewState().render_params()['slip']
    assert params['rush'] == RUSH and params['faults'] == ['rushing']
    assert timeline_boundaries(0.5, rushed=True) == pytest.approx([b * RUSH for b in phase_boundaries(0.5)])


def test_felt_load_follows_the_hold_connected_by_the_hips():
    assert felt_load(0.0, 1.0) == 0.0
    assert felt_load(1.0, 1.0) == 1.0
    assert felt_load(0.9, 0.85) > felt_load(0.4, 0.85) > 0  # a slipping hand feels light
    assert felt_load(0.9, 1.0) > felt_load(0.9, 0.0) > 0  # hip drive lets the arm lean on the water
    assert 0.0 <= felt_load(1.5, 2.0) <= 1.0


def test_load_builds_after_the_catch_peaks_mid_stroke_and_releases_by_the_exit():
    exit = exit_phase(0.5)
    samples = [load_profile(i / 1000, exit) for i in range(1000)]
    assert all(0.0 <= s <= 1.0 for s in samples)
    assert load_profile(0.05, exit) == 0.0  # entry and reach: nothing to push yet
    assert load_profile(CATCH_START, exit) == 0.0 and load_profile(exit, exit) == 0.0
    assert load_profile(0.9, exit) == 0.0  # the recovery is weightless
    peak = max(range(1000), key=lambda i: samples[i]) / 1000
    assert phase_to_step(peak) in {Phase.PULL, Phase.PUSH}
    assert max(samples) == pytest.approx(1.0, abs=1e-4)


@pytest.mark.parametrize('length', [0.0, 0.5, 1.0])
def test_a_heavy_load_slows_the_hand_under_water_and_shortens_the_recovery(length):
    light, heavy = timeline_boundaries(length), timeline_boundaries(length, feel=1.0)
    assert heavy[0] == light[0] == CATCH_START  # the catch keeps its time with the kick
    assert all(h > lo for h, lo in zip(heavy[1:], light[1:], strict=True))
    exit = exit_phase(length)
    assert heavy[-1] - light[-1] == pytest.approx(LOAD_DWELL * (exit - CATCH_START) * (0.5 - LOAD_RELEASE / 3))
    assert 1 - heavy[-1] > 0.15  # the recovery stays a real part of the stroke
    # The hand slows where the load is heaviest: the pull stretches more than the finish.
    assert heavy[2] - heavy[1] - (light[2] - light[1]) > heavy[4] - heavy[3] - (light[4] - light[3])


def test_loaded_time_is_continuous_and_rising_with_rush_and_glide():
    exit = exit_phase(1.0)
    for feel, rush in [(0.0, 1.0), (1.0, 1.0), (1.0, RUSH)]:
        times = [loaded_time(i / 1000 * exit, exit, feel, rush) for i in range(1001)]
        assert all(b > a for a, b in pairwise(times))
        assert max(b - a for a, b in pairwise(times)) < 2 * exit / 1000
        assert times[-1] < 1
    bounds = timeline_boundaries(1.0, rushed=True, glide=100, feel=1.0)
    assert all(b > a for a, b in pairwise(bounds)) and 0 < bounds[0] and bounds[-1] < 1


def test_felt_load_is_a_sensation_only():
    clean, slipping = ViewState(), ViewState(settings=PRESETS['Short slipping'])
    for view in (clean, slipping):
        m = view.metrics()
        assert view.render_params()['feel'] == pytest.approx(felt_load(m.hold_quality, view.settings.drive / 100))
    assert clean.render_params()['feel'] > slipping.render_params()['feel']
    assert ViewState(faults=frozenset({'rushing'})).render_params()['feel'] < clean.render_params()['feel']
    # The arm feels heavier, the swimmer does not: buoyancy still follows pace alone.
    m = clean.metrics()
    assert clean.render_params()['rideHeight'] == waterline_pose(m.distance_per_stroke * 42 / 60)[0]


@pytest.mark.parametrize('distance', [25, 100])
def test_race_finish_matches_distance_and_existing_estimates(distance):
    swimmers = (
        ViewState(settings=StrokeSettings(glide=100)),
        ViewState(settings=PRESETS['Short slipping'], faults=frozenset({'sinking'})),
    )
    race = RaceConfig(swimmers, distance)
    for view, lane, finish in zip(swimmers, race.render_params()['lanes'], race.finish_times(), strict=True):
        assert finish == pytest.approx(view.metrics().seconds_per_25 * distance / 25)
        assert lane['params']['speed'] * lane['finishTime'] == pytest.approx(distance)
        assert lane['params'] == view.render_params()
    assert race.finish_times()[0] < race.finish_times()[1]


def test_solo_race_and_equal_setups():
    view = ViewState(settings=PRESETS['Compact connected'])
    solo = RaceConfig((view,), 100)
    pair = RaceConfig((view, view), 100)
    assert len(solo.render_params()['lanes']) == 1
    assert pair.finish_times() == (solo.finish_times()[0],) * 2
    slower = view.with_fault('rushing', True)
    changed = RaceConfig((view, slower), 100)
    assert changed.finish_times()[1] > changed.finish_times()[0]
    assert pair.swimmers[1].faults == frozenset()


def test_race_rejects_unsupported_setup():
    for count, distance in ((0, 25), (3, 25), (1, 0), (1, 101), (2, 75)):
        with pytest.raises(ValueError):
            RaceConfig((ViewState(),) * count, distance)


def test_pace_support_raises_body_and_reduces_hip_drop_with_bounded_travel():
    slow, middle, fast = (waterline_pose(speed) for speed in (0.24, 0.62, 1.0))
    assert slow[0] < middle[0] < fast[0]
    assert slow[1] > middle[1] > fast[1]
    assert slow == pytest.approx((-0.045, 0.025))
    assert fast == pytest.approx((0.030, 0.0))
    assert waterline_pose(0) == slow
    assert waterline_pose(100) == fast


def test_buoyancy_follows_fault_adjusted_pace_without_changing_metrics():
    clean = ViewState()
    slow = clean.with_fault('sinking', True).with_fault('rushing', True)
    for view in (clean, slow):
        before = view.metrics()
        params = view.render_params()
        assert (params['rideHeight'], params['hipDrop']) == waterline_pose(params['speed'])
        assert view.metrics() == before
    assert slow.render_params()['rideHeight'] < clean.render_params()['rideHeight']


@pytest.mark.parametrize('speed', [-1, math.inf, math.nan])
def test_buoyancy_rejects_invalid_speed(speed):
    with pytest.raises(ValueError):
        waterline_pose(speed)


def test_pace_swolf_and_speed_follow_the_estimates():
    m = StrokeSettings().metrics()
    assert m.seconds_per_100 == pytest.approx(4 * m.seconds_per_25)
    assert m.swolf == pytest.approx(m.strokes_per_25 + m.seconds_per_25)
    assert m.speed * m.seconds_per_25 == pytest.approx(25)
    slipping = PRESETS['Short slipping'].metrics()
    assert slipping.swolf > m.swolf and slipping.speed < m.speed


@pytest.mark.parametrize('breath', [2, 3, 4, 5])
def test_breathing_pattern_costs_nothing_without_a_head_lift_and_reaches_the_engine(breath):
    settings = StrokeSettings(breath=breath)
    assert settings.metrics() == StrokeSettings().metrics()
    assert ViewState(settings=settings).render_params()['breath'] == breath


@pytest.mark.parametrize('breath', [0, 1, 6])
def test_breathing_pattern_rejects_unsupported_counts(breath):
    with pytest.raises(ValueError):
        StrokeSettings(breath=breath)


def test_head_lift_fault_costs_distance_and_has_a_cue():
    clean = ViewState()
    lifted = clean.with_fault('headlift', True)
    assert lifted.metrics().distance_per_stroke < clean.metrics().distance_per_stroke
    assert FAULTS['headlift'].cue
    assert lifted.render_params()['faults'] == ['headlift']


def test_early_exit_cuts_the_finish_short_on_the_timeline_and_in_the_estimates():
    clean, early = ViewState(), ViewState(faults=frozenset({'earlyexit'}))
    length = path_length(42)
    assert FINISH_START < early.exit_phase() < clean.exit_phase() == exit_phase(length)
    assert early.render_params()['exit'] == early.exit_phase()
    bounds = timeline_boundaries(length, early=True)
    assert bounds[:-1] == timeline_boundaries(length)[:-1] and bounds[-1] < timeline_boundaries(length)[-1]
    assert early.metrics().momentum < clean.metrics().momentum  # a shorter drive leaves a longer coast
    assert early.metrics().distance_per_stroke < clean.metrics().distance_per_stroke


def test_dropped_elbow_and_lopsided_pull_weaken_the_catch():
    clean = ViewState()
    for key in ('droppedelbow', 'lopsided', 'earlyroll'):
        view = clean.with_fault(key, True)
        assert view.render_params()['catch'] < clean.render_params()['catch']
        assert view.metrics().hold_quality < clean.metrics().hold_quality
        assert view.render_params()['faults'] == [key] and FAULTS[key].cue
    # A dropped elbow costs more than one weaker arm.
    dropped, lopsided = (clean.with_fault(k, True).metrics().seconds_per_100 for k in ('droppedelbow', 'lopsided'))
    assert dropped > lopsided > clean.metrics().seconds_per_100


def test_drills_are_visual_only_and_validated():
    clean = ViewState()
    for name, drill in DRILLS.items():
        view = ViewState(drill=name)
        assert view.metrics() == clean.metrics()
        params = view.render_params()
        assert params['drill'] == name and params['cycleScale'] == drill.cycle_scale
        assert params['speed'] == clean.render_params()['speed']
    assert DRILLS['catchup'].cycle_scale == 2.0
    assert all(DRILLS[name].cycle_scale == 1.0 for name in ('off', 'single', 'fist'))
    with pytest.raises(ValueError):
        ViewState(drill='kickboard')


def test_races_always_swim_the_full_stroke():
    lane = RaceConfig((ViewState(),), 50).render_params()['lanes'][0]['params']
    assert (lane['drill'], lane['cycleScale']) == ('off', 1.0)


def test_advice_ranks_real_savings_biggest_first():
    view = ViewState(faults=frozenset({'sinking', 'rushing', 'headlift'}))
    tips = advice(view, limit=10)
    savings = [tip.seconds_per_100 for tip in tips]
    assert savings == sorted(savings, reverse=True)
    assert all(saving >= MIN_SAVING for saving in savings)
    before = view.metrics().seconds_per_100
    for tip in tips:
        after = tip.apply(view)
        assert before - after.metrics().seconds_per_100 == pytest.approx(tip.seconds_per_100)
        assert after.settings.rate == view.settings.rate
    assert {tip.fault for tip in tips} >= {'sinking', 'rushing', 'headlift'}
    assert tips[0].fault == 'rushing'
    assert advice(view) == tips[:3]


def test_head_outside_its_band_costs_drag():
    assert head_drag(0) == head_drag(5) == head_drag(15) == 0.0
    assert head_drag(40) == pytest.approx(0.10) and head_drag(-20) == pytest.approx(0.05)
    assert head_drag(25) < head_drag(30) and head_drag(-5) < head_drag(-10)
    assert head_drag(40, sink=1.2) > head_drag(40)  # a lifted head sinks the legs harder at pace
    base = StrokeSettings().metrics().distance_per_stroke
    assert StrokeSettings(head=40).metrics().distance_per_stroke < StrokeSettings(head=25).metrics().distance_per_stroke
    assert StrokeSettings(head=-20).metrics().distance_per_stroke < base
    assert StrokeSettings(head=12).metrics().distance_per_stroke == base
    with pytest.raises(ValueError):
        StrokeSettings(head=41)
    assert ViewState(settings=StrokeSettings(head=-10)).render_params()['head'] == -10


def test_back_arch_beyond_its_band_costs_drag():
    assert arch_drag(0) == arch_drag(8) == 0.0
    assert arch_drag(30) == pytest.approx(0.08) and arch_drag(15) < arch_drag(22)
    assert arch_drag(30, sink=1.2) > arch_drag(30)
    base = StrokeSettings().metrics().distance_per_stroke
    assert StrokeSettings(arch=30).metrics().distance_per_stroke < base
    assert StrokeSettings(arch=6).metrics().distance_per_stroke == base
    with pytest.raises(ValueError):
        StrokeSettings(arch=31)
    assert ViewState(settings=StrokeSettings(arch=12)).render_params()['arch'] == 12
    tip = next(
        t for t in advice(ViewState(settings=StrokeSettings(arch=30)), limit=10) if t.title == 'Ease the back arch'
    )
    assert tip.settings == (('arch', 8),)


def test_advice_levels_a_lifted_or_buried_head():
    for head, level in ((35, 15), (-20, 0)):
        view = ViewState(settings=StrokeSettings(head=head))
        tip = next(tip for tip in advice(view, limit=10) if tip.title == 'Level the head')
        assert tip.settings == (('head', level),)
    assert not any(tip.title == 'Level the head' for tip in advice(ViewState(), limit=10))


def test_advice_changes_one_thing_at_a_time():
    view = ViewState(settings=StrokeSettings(glide=90), faults=frozenset({'crossover'}))
    for tip in advice(view, limit=10):
        after = tip.apply(view)
        keys = ('catch', 'slip', 'drive', 'glide')
        changed = [key for key in keys if getattr(after.settings, key) != getattr(view.settings, key)]
        assert len(changed) + len(view.faults - after.faults) == 1
        for key in changed:
            step = abs(getattr(after.settings, key) - getattr(view.settings, key))
            assert step <= ADVICE_STEP or key == 'glide'
    assert any(tip.settings == (('glide', 50),) for tip in advice(view, limit=10))


def test_advice_is_empty_for_a_clean_ideal_stroke():
    assert advice(ViewState(settings=StrokeSettings(catch=100, slip=0, drive=100))) == ()


def test_advice_apply_keeps_unrelated_view_options():
    view = ViewState(faults=frozenset({'snaking', 'crossover'}), split=True, drill='fist', trail='hands')
    tip = Advice('Fix snaking', 'cue', fault='snaking')
    after = tip.apply(view)
    assert after.faults == frozenset({'crossover'})
    assert (after.split, after.drill, after.trail, after.settings) == (True, 'fist', 'hands', view.settings)


def test_sinking_legs_cost_more_at_a_faster_pace():
    def cost(rate: int) -> float:
        settings = StrokeSettings(rate=rate, kick=0)
        sunk = ViewState(settings=settings, faults=frozenset({'sinking'})).metrics()
        return 1 - sunk.distance_per_stroke / settings.metrics().distance_per_stroke

    assert cost(30) < cost(42) < cost(60)
    assert sink_scale(0.5) < 1.0 < sink_scale(1.4)


def test_good_form_cues_help_and_fix_a_dropped_elbow():
    # Use a weaker catch so the gain is not capped at a perfect hold.
    clean = ViewState(settings=StrokeSettings(catch=70, slip=20))
    base = clean.metrics()
    for key in ('wristpress', 'shoulderreach', 'hipfinish', 'flatpush', 'upsweep', 'paddles'):
        assert FAULTS[key].good and FAULTS[key].cue
        assert clean.with_fault(key, True).metrics().distance_per_stroke > base.distance_per_stroke
        assert not any(a.fault == key for a in advice(clean.with_fault(key, True)))
    dropped = clean.with_fault('droppedelbow', True)
    fixed = dropped.with_fault('wristpress', True).with_fault('shoulderreach', True)
    assert fixed.metrics().distance_per_stroke > dropped.metrics().distance_per_stroke
    assert fixed.render_params()['faults'] == ['droppedelbow', 'shoulderreach', 'wristpress']


def test_hand_paddles_carry_further_but_cost_effort_and_feel_heavier():
    bare = ViewState(settings=StrokeSettings(catch=70, slip=20))
    paddled = bare.with_fault('paddles', True)
    assert FAULTS['paddles'].kit and FAULTS['paddles'].good
    m0, m1 = bare.metrics(), paddled.metrics()
    assert m1.distance_per_stroke > m0.distance_per_stroke
    assert m1.hold_quality > m0.hold_quality
    assert m1.effort > m0.effort
    assert paddled.render_params()['feel'] > bare.render_params()['feel']
    assert felt_load(0.5, 0.5, PADDLE_AREA) == pytest.approx(PADDLE_AREA * felt_load(0.5, 0.5))
    assert felt_load(1.0, 1.0, PADDLE_AREA) == 1.0


def test_a_fast_pace_costs_wave_drag_that_a_slow_one_does_not():
    assert speed_drag(0.5) == speed_drag(HULL_FROM) == 0.0  # the default stroke keeps its calibration
    assert 0 < speed_drag(1.2) < speed_drag(1.4) < speed_drag(2.0)
    assert speed_drag(1.3, height=150) > speed_drag(1.3) > speed_drag(1.3, height=200)  # a longer hull is freer
    rates = range(22, 73, 2)
    speeds = [StrokeSettings(rate=r, kick=100, beats=6).metrics().distance_per_stroke * r / 60 for r in rates]
    assert all(b > a for a, b in pairwise(speeds))  # waves never make a higher rate slower
