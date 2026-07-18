# -*- coding: utf-8 -*-
"""Pure offline-model tests for Expert Candidate Lab v2.

No link, worker, serial port, vendor DLL, or Qt object is constructed here.
"""

import math

import pytest

import expert_tuning_offline as expert


R_PP_OHM = 0.119
L_PP_H = 35.7e-6
TS_S = 100e-6
KA_STAR = 5.794e6
B_VISCOUS = 1e-7
KP1_MODEL = 0.07177
KI1_MODEL_HZ = 812.939


def _current_model_pair():
    plant = expert.CurrentPlant(0.139, 41.6e-6, TS_S)
    candidate = expert.evaluate_manual_current_candidate(
        plant, kp_v_per_a=KP1_MODEL, ki_hz=KI1_MODEL_HZ)
    assert candidate.design_passed
    return plant, candidate


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


def test_known_velocity_position_model_reproduces_frozen_single_point():
    current_plant, current_candidate = _current_model_pair()
    plant = expert.VelocityPositionPlant(
        current_plant=current_plant,
        current_candidate=current_candidate,
        accel_constant_cnt_per_s2_per_a_peak=KA_STAR,
        viscous_friction_a_peak_per_cnt_s=B_VISCOUS,
    )

    candidate = expert.design_velocity_position_candidate(plant)

    assert candidate.model_status == expert.MODEL_STATUS
    assert candidate.velocity_basis == expert.ENCODER_COUNTS_PER_SECOND
    assert candidate.current_basis == expert.PEAK_AMPERES
    assert candidate.d_visc_per_s == pytest.approx(0.5794)
    assert candidate.design_bandwidth_rad_s == pytest.approx(457.5)
    assert candidate.kp_vel_a_per_cnt_s == pytest.approx(
        7.8961e-5, rel=5e-4)
    assert candidate.ki_vel_hz == pytest.approx(10.69998, rel=5e-4)
    assert candidate.kp_pos_per_s == pytest.approx(85.2114, rel=5e-4)
    assert candidate.velocity_crossover_hz == pytest.approx(73.9, abs=2.0)
    assert candidate.velocity_phase_margin_deg == pytest.approx(
        67.6, abs=1.0)
    assert candidate.velocity_gain_margin_db == pytest.approx(15.0, abs=0.5)
    assert candidate.position_phase_margin_deg == pytest.approx(81.1, abs=1.0)
    assert candidate.loop_model_passed is True
    assert candidate.reductions == 0
    assert candidate.current_source == "MANUAL"

    # Analytic identities independently pin the three calibrated gain laws.
    assert (candidate.kp_vel_a_per_cnt_s * KA_STAR
            == pytest.approx(candidate.design_bandwidth_rad_s, rel=1e-12))
    assert (2.0 * math.pi * 6.805 * candidate.ki_vel_hz
            == pytest.approx(candidate.design_bandwidth_rad_s, rel=1e-12))
    assert (5.369 * candidate.kp_pos_per_s
            == pytest.approx(candidate.design_bandwidth_rad_s, rel=1e-12))


def test_velocity_position_model_is_deterministic_and_immutable():
    current_plant, current_candidate = _current_model_pair()
    plant = expert.VelocityPositionPlant(
        current_plant, current_candidate, KA_STAR, B_VISCOUS)

    first = expert.design_velocity_position_candidate(plant)
    second = expert.design_velocity_position_candidate(plant)

    assert first == second
    with pytest.raises(Exception):
        first.kp_pos_per_s = 1.0


def test_zero_viscous_friction_is_a_valid_limiting_case():
    current_plant, current_candidate = _current_model_pair()
    plant = expert.VelocityPositionPlant(
        current_plant, current_candidate, KA_STAR, 0.0)

    candidate = expert.design_velocity_position_candidate(plant)

    assert candidate.d_visc_per_s == 0.0
    assert math.isfinite(candidate.kp_vel_a_per_cnt_s)
    assert math.isfinite(candidate.position_phase_margin_deg)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("accel_constant_cnt_per_s2_per_a_peak", True),
        ("accel_constant_cnt_per_s2_per_a_peak", 0.0),
        ("accel_constant_cnt_per_s2_per_a_peak", -1.0),
        ("accel_constant_cnt_per_s2_per_a_peak", math.nan),
        ("accel_constant_cnt_per_s2_per_a_peak", math.inf),
        ("accel_constant_cnt_per_s2_per_a_peak", 1.0),
        ("accel_constant_cnt_per_s2_per_a_peak", 3.1e8),
        ("viscous_friction_a_peak_per_cnt_s", True),
        ("viscous_friction_a_peak_per_cnt_s", -1e-7),
        ("viscous_friction_a_peak_per_cnt_s", math.nan),
        ("viscous_friction_a_peak_per_cnt_s", math.inf),
    ),
)
def test_velocity_position_plant_rejects_invalid_or_out_of_model_inputs(
        field, value):
    current_plant, current_candidate = _current_model_pair()
    values = {
        "current_plant": current_plant,
        "current_candidate": current_candidate,
        "accel_constant_cnt_per_s2_per_a_peak": KA_STAR,
        "viscous_friction_a_peak_per_cnt_s": B_VISCOUS,
    }
    values[field] = value

    with pytest.raises(ValueError):
        expert.VelocityPositionPlant(**values)


@pytest.mark.parametrize(
    ("velocity_basis", "current_basis"),
    (
        ("rpm", expert.PEAK_AMPERES),
        (expert.ENCODER_COUNTS_PER_SECOND, "rms-amperes"),
    ),
)
def test_velocity_position_plant_rejects_implicit_unit_conversion(
        velocity_basis, current_basis):
    current_plant, current_candidate = _current_model_pair()

    with pytest.raises(ValueError):
        expert.VelocityPositionPlant(
            current_plant, current_candidate, KA_STAR, B_VISCOUS,
            velocity_basis=velocity_basis,
            current_basis=current_basis,
        )


@pytest.mark.parametrize("sampling_time_s", (38e-6, 41e-6, 122e-6))
def test_velocity_position_model_rejects_out_of_drive_ts_contract(
        sampling_time_s):
    current_plant = expert.CurrentPlant(0.139, 41.6e-6, sampling_time_s)
    current_candidate = expert.evaluate_manual_current_candidate(
        current_plant, kp_v_per_a=KP1_MODEL, ki_hz=KI1_MODEL_HZ)
    plant = expert.VelocityPositionPlant(
        current_plant, current_candidate, KA_STAR, B_VISCOUS)

    with pytest.raises(ValueError, match="TS"):
        expert.design_velocity_position_candidate(plant)


def test_failed_or_mismatched_current_model_cannot_feed_p2():
    current_plant, current_candidate = _current_model_pair()
    failed = expert.CurrentCandidate(
        kp_v_per_a=current_candidate.kp_v_per_a,
        ki_hz=current_candidate.ki_hz,
        crossover_hz=current_candidate.crossover_hz,
        phase_margin_deg=current_candidate.phase_margin_deg,
        target_bandwidth_hz=None,
        design_passed=False,
        source="MUTATED",
        basis=current_candidate.basis,
    )
    mismatched = expert.CurrentCandidate(
        kp_v_per_a=current_candidate.kp_v_per_a,
        ki_hz=current_candidate.ki_hz,
        crossover_hz=current_candidate.crossover_hz,
        phase_margin_deg=current_candidate.phase_margin_deg,
        target_bandwidth_hz=None,
        design_passed=True,
        source="MUTATED",
        basis="phase-to-neutral",
    )

    for invalid_candidate in (failed, mismatched):
        with pytest.raises(ValueError):
            expert.VelocityPositionPlant(
                current_plant, invalid_candidate, KA_STAR, B_VISCOUS)


def test_current_candidate_must_be_coherent_with_the_exact_p2_plant():
    current_plant, _current_candidate = _current_model_pair()
    other_plant = expert.CurrentPlant(1.0, 1e-3, TS_S)
    stale_candidate = expert.design_current_candidate(other_plant)
    assert stale_candidate.design_passed

    with pytest.raises(ValueError, match="current.*(plant|coher)"):
        expert.VelocityPositionPlant(
            current_plant, stale_candidate, KA_STAR, B_VISCOUS)


def test_accel_constant_mutation_has_the_expected_gain_sensitivity():
    current_plant, current_candidate = _current_model_pair()
    baseline = expert.design_velocity_position_candidate(
        expert.VelocityPositionPlant(
            current_plant, current_candidate, KA_STAR, B_VISCOUS))
    doubled = expert.design_velocity_position_candidate(
        expert.VelocityPositionPlant(
            current_plant, current_candidate, 2.0 * KA_STAR, B_VISCOUS))

    assert doubled.kp_vel_a_per_cnt_s == pytest.approx(
        0.5 * baseline.kp_vel_a_per_cnt_s)
    assert doubled.ki_vel_hz == pytest.approx(baseline.ki_vel_hz)
    assert doubled.kp_pos_per_s == pytest.approx(baseline.kp_pos_per_s)


@pytest.mark.parametrize(
    "mutation",
    (
        {"kp2": -1.0},
        {"margins": {"w_ci": 1.0, "pm_i": 50.0, "w_cv": 1.0,
                     "pm_vel": math.nan, "gm_db": 10.0,
                     "w_cp": 1.0, "pm_pos": 80.0}},
        {"iters": ({}, {}, {}, {}, {})},
    ),
)
def test_velocity_position_wrapper_rejects_malformed_delegate_output(
        monkeypatch, mutation):
    current_plant, current_candidate = _current_model_pair()
    params = expert.autotune_velpos.AutotuneVPParams(
        r_pp_ohm=current_plant.resistance_ohm,
        l_pp_h=current_plant.inductance_h,
    )
    valid = dict(expert.autotune_velpos.design_vp_gains(
        KA_STAR,
        KA_STAR * B_VISCOUS,
        TS_S,
        params,
        current_candidate.kp_v_per_a,
        current_candidate.ki_hz,
    ))
    valid["margins"] = dict(valid["margins"])
    valid["iters"] = tuple(dict(item) for item in valid["iters"])
    valid.update(mutation)
    monkeypatch.setattr(
        expert.autotune_velpos, "design_vp_gains",
        lambda *_args, **_kwargs: valid)
    plant = expert.VelocityPositionPlant(
        current_plant, current_candidate, KA_STAR, B_VISCOUS)

    with pytest.raises(ValueError):
        expert.design_velocity_position_candidate(plant)


def test_velocity_position_wrapper_rejects_contradictory_delegate_gate(
        monkeypatch):
    current_plant, current_candidate = _current_model_pair()
    contradictory = {
        "ok": True,
        "kp2": 457.5 / KA_STAR,
        "ki2": 457.5 / (2.0 * math.pi * 6.805),
        "kp3": 457.5 / 5.369,
        "wcv": 457.5,
        "margins": {
            "w_ci": 2000.0,
            "pm_i": -25.0,
            "w_cv": 400.0,
            "pm_vel": -10.0,
            "gm_db": -6.0,
            "w_cp": 80.0,
            "pm_pos": -15.0,
        },
        "iters": ({
            "wcv_rad_s": 457.5,
            "kp2": 457.5 / KA_STAR,
            "ki2_hz": 457.5 / (2.0 * math.pi * 6.805),
            "kp3": 457.5 / 5.369,
            "pm_vel": -10.0,
            "gm_db": -6.0,
            "pm_pos": -15.0,
            "wcv_ts": 0.04575,
            "pass": False,
        },),
    }
    monkeypatch.setattr(
        expert.autotune_velpos, "design_vp_gains",
        lambda *_args, **_kwargs: contradictory)
    plant = expert.VelocityPositionPlant(
        current_plant, current_candidate, KA_STAR, B_VISCOUS)

    with pytest.raises(ValueError, match="gate|margin|trace"):
        expert.design_velocity_position_candidate(plant)


def test_velocity_position_wrapper_recomputes_delegate_margins(
        monkeypatch):
    current_plant, current_candidate = _current_model_pair()
    fabricated = {
        "ok": True,
        "kp2": 457.5 / KA_STAR,
        "ki2": 457.5 / (2.0 * math.pi * 6.805),
        "kp3": 457.5 / 5.369,
        "wcv": 457.5,
        "margins": {
            "w_ci": 3000.0,
            "pm_i": 80.0,
            "w_cv": 600.0,
            "pm_vel": 80.0,
            "gm_db": 20.0,
            "w_cp": 120.0,
            "pm_pos": 85.0,
        },
        "iters": ({
            "wcv_rad_s": 457.5,
            "kp2": 457.5 / KA_STAR,
            "ki2_hz": 457.5 / (2.0 * math.pi * 6.805),
            "kp3": 457.5 / 5.369,
            "pm_vel": 80.0,
            "gm_db": 20.0,
            "pm_pos": 85.0,
            "wcv_ts": 0.04575,
            "pass": True,
        },),
    }
    monkeypatch.setattr(
        expert.autotune_velpos, "design_vp_gains",
        lambda *_args, **_kwargs: fabricated)
    plant = expert.VelocityPositionPlant(
        current_plant, current_candidate, KA_STAR, B_VISCOUS)

    with pytest.raises(ValueError, match="margin"):
        expert.design_velocity_position_candidate(plant)
