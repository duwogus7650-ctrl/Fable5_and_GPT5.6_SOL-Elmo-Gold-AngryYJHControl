# -*- coding: utf-8 -*-
"""Pure offline-model tests for Expert Candidate Lab v1.

No link, worker, serial port, vendor DLL, or Qt object is constructed here.
"""

import math

import pytest

import expert_tuning_offline as expert


R_PP_OHM = 0.119
L_PP_H = 35.7e-6
TS_S = 100e-6


def test_known_phase_to_phase_plant_reproduces_frozen_candidate():
    plant = expert.CurrentPlant(
        resistance_ohm=R_PP_OHM,
        inductance_h=L_PP_H,
        sampling_time_s=TS_S,
        basis=expert.PHASE_TO_PHASE,
    )

    candidate = expert.design_current_candidate(plant)

    assert candidate.model_status == "MODEL"
    assert candidate.basis == expert.PHASE_TO_PHASE
    assert candidate.kp_v_per_a == pytest.approx(0.07177, rel=0.005)
    assert candidate.ki_hz == pytest.approx(812.94, rel=0.005)
    assert candidate.phase_margin_deg >= 45.0
    assert candidate.design_passed is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resistance_ohm": 0.0},
        {"resistance_ohm": -0.1},
        {"inductance_h": 0.0},
        {"inductance_h": float("nan")},
        {"sampling_time_s": float("inf")},
        {"sampling_time_s": 0.0},
        {"basis": "phase_to_neutral"},
    ],
)
def test_plant_validation_rejects_ambiguous_or_nonphysical_inputs(kwargs):
    values = {
        "resistance_ohm": R_PP_OHM,
        "inductance_h": L_PP_H,
        "sampling_time_s": TS_S,
        "basis": expert.PHASE_TO_PHASE,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        expert.CurrentPlant(**values)


def test_manual_candidate_is_separate_from_plant_and_reports_model_margin():
    plant = expert.CurrentPlant(
        resistance_ohm=R_PP_OHM,
        inductance_h=L_PP_H,
        sampling_time_s=TS_S,
    )

    candidate = expert.evaluate_manual_current_candidate(
        plant, kp_v_per_a=0.06, ki_hz=600.0)

    assert candidate.source == "MANUAL"
    assert candidate.kp_v_per_a == 0.06
    assert candidate.ki_hz == 600.0
    assert math.isfinite(candidate.crossover_hz)
    assert math.isfinite(candidate.phase_margin_deg)


@pytest.mark.parametrize(
    "kp,ki",
    [
        (0.0, 100.0),
        (-1.0, 100.0),
        (0.1, 0.0),
        (0.1, float("nan")),
        (float("inf"), 100.0),
    ],
)
def test_manual_candidate_rejects_invalid_gains(kp, ki):
    plant = expert.CurrentPlant(R_PP_OHM, L_PP_H, TS_S)

    with pytest.raises(ValueError):
        expert.evaluate_manual_current_candidate(
            plant, kp_v_per_a=kp, ki_hz=ki)


def test_frequency_response_is_bounded_deterministic_and_chart_ready():
    plant = expert.CurrentPlant(R_PP_OHM, L_PP_H, TS_S)
    candidate = expert.design_current_candidate(plant)

    first = expert.current_frequency_response(
        plant, candidate, f_min_hz=10.0, f_max_hz=5000.0, points=241)
    second = expert.current_frequency_response(
        plant, candidate, f_min_hz=10.0, f_max_hz=5000.0, points=241)

    assert first == second
    assert len(first.frequency_hz) == 241
    assert first.frequency_hz[0] == pytest.approx(10.0)
    assert first.frequency_hz[-1] == pytest.approx(5000.0)
    assert all(a < b for a, b in zip(
        first.frequency_hz, first.frequency_hz[1:]))
    assert all(math.isfinite(value) for series in (
        first.plant_magnitude_db,
        first.open_loop_magnitude_db,
        first.open_loop_phase_deg,
        first.closed_loop_magnitude_db,
    ) for value in series)
    assert min(first.open_loop_magnitude_db) < 0.0
    assert max(first.open_loop_magnitude_db) > 0.0


def test_frequency_response_bounds_and_point_budget_fail_closed():
    plant = expert.CurrentPlant(R_PP_OHM, L_PP_H, TS_S)
    candidate = expert.design_current_candidate(plant)

    for kwargs in (
        {"f_min_hz": 0.0},
        {"f_min_hz": 100.0, "f_max_hz": 100.0},
        {"f_max_hz": float("inf")},
        {"points": 31},
        {"points": 5001},
    ):
        with pytest.raises(ValueError):
            expert.current_frequency_response(plant, candidate, **kwargs)


def test_phase_line_basis_negative_control_cannot_silently_halve_the_plant():
    with pytest.raises(ValueError, match="phase-to-phase"):
        expert.CurrentPlant(
            resistance_ohm=R_PP_OHM / 2.0,
            inductance_h=L_PP_H / 2.0,
            sampling_time_s=TS_S,
            basis="phase-to-neutral",
        )
