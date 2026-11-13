"""Unit tests for the pure stroke model: timing, phases, estimates, faults, and validation."""

import math
from dataclasses import astuple

import pytest

from long_catch.model import (
    FAULTS,
    PRESETS,
    RUSH,
    Phase,
    RaceConfig,
    StrokeSettings,
    ViewState,
    arm_phases,
    cycle_duration,
    estimate_metrics,
    exit_phase,
    format_duration,
    highlight_intensity,
    matching_preset,
    path_length,
    phase_boundaries,
    phase_to_step,
    timeline_boundaries,
    waterline_pose,
)


def test_cycle_duration_at_40_spm():
    assert cycle_duration(40) == 3.0


def test_cycle_duration_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        cycle_duration(0)


@pytest.mark.parametrize(
    ('phase', 'expected'),
    [(0.0, (0.0, 0.5)), (1.25, (0.25, 0.75))],
)
def test_arms_are_half_a_cycle_apart(phase, expected):
    assert arm_phases(phase) == pytest.approx(expected)


@pytest.mark.parametrize(
    ('phase', 'expected'),
    [
        (0.0, Phase.ENTRY),
        (0.1199, Phase.ENTRY),
        (0.12, Phase.CATCH),
        (0.30, Phase.PULL),
        (0.66, Phase.FINISH),
        (0.7401, Phase.RECOVERY),
        (-0.05, Phase.RECOVERY),
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


@pytest.mark.parametrize(
    ('seconds', 'expected'),
    [(33.46, '33.5 s'), (59.96, '1:00.0'), (-1, '–')],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


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


def test_outputs_are_finite_and_consistent():
    result = estimate_metrics(0.9, 0.1, 0.7, 40)
    assert all(math.isfinite(value) for value in astuple(result))
    assert result.strokes_per_25 == pytest.approx(25 / result.distance_per_stroke)
    assert result.seconds_per_25 == pytest.approx(result.strokes_per_25 * 60 / 40)


def test_highlight_intensity_range():
    assert highlight_intensity(0, 0) == pytest.approx(0.15)
    assert highlight_intensity(1, 1) == pytest.approx(1.0)
    assert highlight_intensity(0.9, 0.85) > highlight_intensity(0.5, 0.35)


def test_settings_validate_ranges():
    with pytest.raises(ValueError):
        StrokeSettings(rate=10)
    with pytest.raises(ValueError):
        StrokeSettings(slip=101)
    for kick in (-1, 101):
        with pytest.raises(ValueError):
            StrokeSettings(kick=kick)
    assert StrokeSettings().with_values(slip=20).slip == 20


def test_view_state_rejects_unknown_emphasis_and_playback():
    with pytest.raises(ValueError):
        ViewState(emphasis='legs')
    with pytest.raises(ValueError):
        ViewState(playback=3.0)


def test_view_options_validate_and_trail_reaches_the_engine():
    for bad in ({'angle': 'behind'}, {'trail': 'elbows'}, {'trail_seconds': 9.0}):
        with pytest.raises(ValueError):
            ViewState(**bad)
    params = ViewState(trail='hands', trail_seconds=3.0).render_params()
    assert (params['trail'], params['trailSeconds']) == ('hands', 3.0)


def test_holding_follows_hold_quality_threshold():
    assert PRESETS['Long power'].metrics().holding
    assert not PRESETS['Short slipping'].metrics().holding


def test_matching_preset_identifies_unchanged_presets_only():
    assert all(matching_preset(settings) == name for name, settings in PRESETS.items())
    assert matching_preset(PRESETS['Long power'].with_values(kick=0)) is None


def test_presets_differ_and_rank_sensibly():
    metrics = {name: s.metrics().distance_per_stroke for name, s in PRESETS.items()}
    assert len(set(PRESETS.values())) == 4
    assert metrics['Long power'] > metrics['Compact connected'] > metrics['Short slipping']


def test_render_params_are_fractions():
    params = ViewState().render_params()
    for key in ('catch', 'slip', 'drive', 'kick', 'length', 'exit', 'intensity'):
        assert 0 <= params[key] <= 1
    assert params['exit'] == exit_phase(params['length'])


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


@pytest.mark.parametrize('distance', [25, 50, 100])
def test_race_finish_matches_distance_and_existing_estimates(distance):
    swimmers = (ViewState(), ViewState(settings=PRESETS['Short slipping'], faults=frozenset({'sinking'})))
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


@pytest.mark.parametrize(('count', 'distance'), [(0, 25), (3, 25), (1, 0), (1, 101), (2, 75)])
def test_race_rejects_unsupported_setup(count, distance):
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
