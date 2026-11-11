import math
from dataclasses import astuple

import pytest

from long_catch.model import (
    FAULTS,
    PRESETS,
    RUSH,
    Phase,
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
        (0.62, Phase.FINISH),
        (0.7201, Phase.RECOVERY),
        (-0.05, Phase.RECOVERY),
    ],
)
def test_phase_to_step_boundaries(phase, expected):
    assert phase_to_step(phase, length=0.5) == expected


def test_longer_stroke_stays_underwater_longer():
    assert exit_phase(1.0) > exit_phase(0.0)
    assert phase_to_step(0.74, length=1.0) == Phase.FINISH
    assert phase_to_step(0.74, length=0.0) == Phase.RECOVERY


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
