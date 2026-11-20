"""Unit tests for the pure stroke model: timing, phases, estimates, faults, and validation."""

import math
from dataclasses import astuple
from itertools import pairwise

import pytest

from long_catch.model import (
    ADVICE_STEP,
    CATCH_START,
    DRILLS,
    FAULTS,
    LOAD_DWELL,
    LOAD_RELEASE,
    MIN_SAVING,
    PRESETS,
    RUSH,
    Advice,
    Phase,
    RaceConfig,
    StrokeSettings,
    ViewState,
    advice,
    arm_phases,
    cycle_duration,
    estimate_metrics,
    exit_phase,
    felt_load,
    format_duration,
    load_profile,
    loaded_time,
    matching_preset,
    momentum_carry,
    path_length,
    phase_boundaries,
    phase_to_step,
    stroke_phase,
    stroke_time,
    timeline_boundaries,
    waterline_pose,
)


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


def test_path_length_shortens_with_rate():
    assert path_length(32) == 1.0
    assert path_length(72) == 0.0
    assert path_length(38) > path_length(54)


def test_format_duration_carries_rounded_seconds_into_the_next_minute():
    assert format_duration(59.96) == '1:00.0'


def test_more_slip_reduces_distance_per_stroke():
    low_slip = estimate_metrics(0.9, 0.1, 0.7, 40)
    high_slip = estimate_metrics(0.9, 0.7, 0.7, 40)
    assert high_slip.distance_per_stroke < low_slip.distance_per_stroke


def test_better_catch_improves_distance_per_stroke():
    poor = estimate_metrics(0.3, 0.1, 0.7, 40)
    good = estimate_metrics(0.9, 0.1, 0.7, 40)
    assert good.distance_per_stroke > poor.distance_per_stroke


def test_drive_cannot_rescue_poor_catch_and_slip():
    poor_full_drive = estimate_metrics(0.3, 0.7, 1.0, 40)
    good_no_drive = estimate_metrics(0.9, 0.1, 0.0, 40)
    assert poor_full_drive.distance_per_stroke < good_no_drive.distance_per_stroke


def test_low_rate_loses_momentum_and_distance_in_the_glide():
    slow, quick = estimate_metrics(0.9, 0.1, 0.7, 30), estimate_metrics(0.9, 0.1, 0.7, 50)
    assert 0 < slow.momentum < quick.momentum <= 1
    assert slow.seconds_per_25 > estimate_metrics(0.9, 0.1, 0.7, 42).seconds_per_25
    assert momentum_carry(200) == 1.0


def test_slow_long_stroke_reaches_further_only_when_holding_water():
    m = StrokeSettings(rate=22).metrics()
    assert m.strokes_per_25 == pytest.approx(12.8, abs=0.2)
    assert m.seconds_per_25 * 4 == pytest.approx(138, abs=2)
    slipping = estimate_metrics(0.3, 0.7, 1.0, 22).distance_per_stroke
    assert slipping < estimate_metrics(0.3, 0.7, 1.0, 42).distance_per_stroke + 0.3 < m.distance_per_stroke


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


def test_pull_width_and_kick_timing_are_visual_only():
    base = StrokeSettings()
    other = base.with_values(width=100, beats=6)
    assert base.metrics() == other.metrics()
    params = ViewState(settings=other, pressure=True).render_params()
    assert (params['width'], params['beats'], params['pressure']) == (1, 6, True)
    for beats in (3, 8):
        with pytest.raises(ValueError):
            StrokeSettings(beats=beats)


def test_outputs_are_finite_and_consistent():
    result = estimate_metrics(0.9, 0.1, 0.7, 40)
    assert all(math.isfinite(value) for value in astuple(result))
    assert result.strokes_per_25 == pytest.approx(25 / result.distance_per_stroke)
    assert result.seconds_per_25 == pytest.approx(result.strokes_per_25 * 60 / 40)
    params = ViewState().render_params()
    assert all(0 <= params[key] <= 1 for key in ('catch', 'slip', 'drive', 'kick', 'length', 'exit', 'intensity'))
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
        {'emphasis': 'legs'},
        {'playback': 3.0},
    ):
        with pytest.raises(ValueError):
            ViewState(**bad)
    params = ViewState(trail='hands', trail_seconds=3.0).render_params()
    assert (params['trail'], params['trailSeconds']) == ('hands', 3.0)


def test_matching_preset_identifies_unchanged_presets_only():
    assert all(matching_preset(settings) == name for name, settings in PRESETS.items())
    assert matching_preset(PRESETS['Long power'].with_values(kick=0)) is None
    metrics = {name: s.metrics().distance_per_stroke for name, s in PRESETS.items()}
    assert len(set(PRESETS.values())) == 4
    assert metrics['Long power'] > metrics['Compact connected'] > metrics['Short slipping']


def test_kick_control_is_visual_only_and_normalized():
    still = StrokeSettings(kick=0)
    strong = still.with_values(kick=100)
    assert still.metrics() == strong.metrics()
    assert ViewState(settings=still).render_params()['kick'] == 0
    assert ViewState(settings=strong).render_params()['kick'] == 1


def test_entry_angle_is_visual_only_and_passed_in_degrees():
    flat = StrokeSettings(entry=0)
    steep = flat.with_values(entry=40)
    assert flat.metrics() == steep.metrics()
    assert ViewState(settings=steep).render_params()['entry'] == 40
    with pytest.raises(ValueError):
        StrokeSettings(entry=41)


def test_stroke_depth_is_visual_only_and_normalized():
    shallow = StrokeSettings(depth=0)
    deep = shallow.with_values(depth=100)
    assert shallow.metrics() == deep.metrics()
    assert ViewState(settings=deep).render_params()['depth'] == 1
    with pytest.raises(ValueError):
        StrokeSettings(depth=101)


def test_every_fault_costs_distance_and_unknown_faults_are_rejected():
    clean = ViewState().metrics().distance_per_stroke
    for key in FAULTS:
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
def test_breathing_pattern_is_visual_only_and_reaches_the_engine(breath):
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
