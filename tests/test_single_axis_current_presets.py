"""Pure contracts for the EAS-shaped, output-locked Current presets."""

from __future__ import annotations

import math

import pytest

import single_axis_current_presets as presets


def test_five_zero_amp_presets_match_the_observed_eas_shape():
    model = presets.build_current_command_presets((0.0,) * 5)

    assert len(model) == 5
    assert tuple(item.index for item in model) == (1, 2, 3, 4, 5)
    assert all(item.value_a == 0.0 for item in model)
    assert all(item.command_register == "TC" for item in model)
    assert all(item.output_locked is True for item in model)
    assert all(item.command_preview == "TC=0" for item in model)
    assert all("LIMITS UNKNOWN" in item.status for item in model)


def test_observed_current_limits_classify_local_drafts_without_drive_io():
    model = presets.build_current_command_presets(
        (0.5, 2.0, 2.1, 4.1, -5.1),
        continuous_limit_a=2.0,
        peak_limit_a=4.0,
        maximum_drive_current_a=5.0,
    )

    assert model[0].status == "LOCAL DRAFT / WITHIN OBSERVED LIMITS"
    assert model[1].status == "LOCAL DRAFT / WITHIN OBSERVED LIMITS"
    assert model[2].status == "WARNING / ABOVE CONTINUOUS LIMIT"
    assert model[3].status == "WARNING / ABOVE PEAK LIMIT"
    assert model[4].status == "INVALID / ABOVE DRIVE MAXIMUM"
    assert all(item.output_locked is True for item in model)


@pytest.mark.parametrize(
    "values",
    (
        (),
        (0.0,) * 4,
        (0.0,) * 6,
        (0.0, 0.0, 0.0, 0.0, math.nan),
        (0.0, 0.0, 0.0, 0.0, math.inf),
    ),
)
def test_invalid_preset_sets_fail_closed(values):
    with pytest.raises(ValueError):
        presets.build_current_command_presets(values)


@pytest.mark.parametrize(
    "limits",
    (
        {"continuous_limit_a": 0.0},
        {"continuous_limit_a": math.nan},
        {"continuous_limit_a": 3.0, "peak_limit_a": 2.0},
        {"peak_limit_a": 6.0, "maximum_drive_current_a": 5.0},
    ),
)
def test_invalid_or_inconsistent_limit_evidence_fails_closed(limits):
    with pytest.raises(ValueError):
        presets.build_current_command_presets((0.0,) * 5, **limits)
