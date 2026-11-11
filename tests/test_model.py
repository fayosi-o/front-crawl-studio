import math

import pytest

from long_catch.model import (
    PRESETS,
    Phase,
    StrokeSettings,
    ViewState,
    arm_phases,
    clamp,
    cycle_duration,
    estimate_metrics,
    exit_phase,
    format_duration,
    highlight_intensity,
    path_length,
    phase_to_step,
)


def test_clamp_bounds():
    assert clamp(-1, 0, 1) == 0
    assert clamp(2, 0, 1) == 1
    assert clamp(0.4, 0, 1) == 0.4


def test_cycle_duration_at_40_spm():
    assert cycle_duration(40) == 3.0


@pytest.mark.parametrize('rate', [0, -10])
def test_cycle_duration_rejects_non_positive_rate(rate):
    with pytest.raises(ValueError):
        cycle_duration(rate)


@pytest.mark.parametrize(
    ('phase', 'expected'),
    [(0.0, (0.0, 0.5)), (0.25, (0.25, 0.75)), (0.5, (0.5, 0.0)), (0.75, (0.75, 0.25)), (1.25, (0.25, 0.75))],
)
def test_arms_are_half_a_cycle_apart(phase, expected):
    assert arm_phases(phase) == pytest.approx(expected)


@pytest.mark.parametrize(
    ('phase', 'expected'),
    [
        (0.0, Phase.ENTRY),
        (0.1199, Phase.ENTRY),
        (0.12, Phase.CATCH),
        (0.2999, Phase.CATCH),
        (0.30, Phase.PULL),
        (0.6199, Phase.PULL),
        (0.62, Phase.FINISH),
        (0.70, Phase.FINISH),
        (0.7201, Phase.RECOVERY),
        (0.9999, Phase.RECOVERY),
        (1.0, Phase.ENTRY),
        (-0.05, Phase.RECOVERY),
    ],
)
def test_phase_to_step_boundaries(phase, expected):
    assert phase_to_step(phase, length=0.5) == expected


def test_longer_stroke_stays_underwater_longer():
    assert exit_phase(1.0) > exit_phase(0.0)
    assert phase_to_step(0.74, length=1.0) == Phase.FINISH
    assert phase_to_step(0.74, length=0.0) == Phase.RECOVERY


def test_phase_labels():
    assert [p.label for p in Phase] == ['Entry & reach', 'Catch', 'Pull', 'Finish', 'Recovery']


def test_path_length_shortens_with_rate():
    assert path_length(32) == 1.0
    assert path_length(72) == 0.0
    assert path_length(38) > path_length(54)


@pytest.mark.parametrize(
    ('seconds', 'expected'),
    [(0, '0.0 s'), (33.46, '33.5 s'), (59.96, '1:00.0'), (75.25, '1:15.2'), (-1, '–'), (math.inf, '–')],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_more_slip_reduces_distance_per_stroke():
    low_slip = estimate_metrics(0.9, 0.1, 0.7, 40)
    high_slip = estimate_metrics(0.9, 0.7, 0.7, 40)
    assert high_slip['distance_per_stroke'] < low_slip['distance_per_stroke']


def test_better_catch_improves_distance_per_stroke():
    poor = estimate_metrics(0.3, 0.1, 0.7, 40)
    good = estimate_metrics(0.9, 0.1, 0.7, 40)
    assert good['distance_per_stroke'] > poor['distance_per_stroke']


def test_drive_cannot_rescue_poor_catch_and_slip():
    poor_full_drive = estimate_metrics(0.3, 0.7, 1.0, 40)
    good_no_drive = estimate_metrics(0.9, 0.1, 0.0, 40)
    assert poor_full_drive['distance_per_stroke'] < good_no_drive['distance_per_stroke']


def test_outputs_are_finite_and_consistent():
    result = estimate_metrics(0.9, 0.1, 0.7, 40)
    assert all(math.isfinite(value) for value in result.values())
    assert result['strokes_per_25'] == pytest.approx(25 / result['distance_per_stroke'])
    assert result['seconds_per_25'] == pytest.approx(result['strokes_per_25'] * 60 / 40)


def test_highlight_intensity_range():
    assert highlight_intensity(0, 0) == pytest.approx(0.15)
    assert highlight_intensity(1, 1) == pytest.approx(1.0)
    assert highlight_intensity(0.9, 0.85) > highlight_intensity(0.5, 0.35)


def test_settings_validate_ranges():
    with pytest.raises(ValueError):
        StrokeSettings(rate=10)
    with pytest.raises(ValueError):
        StrokeSettings(slip=101)
    assert StrokeSettings().with_values(slip=20).slip == 20


def test_view_state_rejects_unknown_emphasis():
    with pytest.raises(ValueError):
        ViewState(emphasis='legs')


def test_presets_differ_and_rank_sensibly():
    metrics = {name: s.metrics()['distance_per_stroke'] for name, s in PRESETS.items()}
    assert len(set(PRESETS.values())) == 4
    assert metrics['Long power'] > metrics['Compact connected'] > metrics['Short slipping']


def test_render_params_are_fractions():
    params = ViewState().render_params()
    for key in ('catch', 'slip', 'drive', 'length', 'exit', 'intensity'):
        assert 0 <= params[key] <= 1
    assert params['exit'] == exit_phase(params['length'])
