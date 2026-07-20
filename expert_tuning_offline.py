"""Pure offline P1/P2 design models for Expert Candidate Lab v2.

This module intentionally owns no transport, worker, Qt, vendor-DLL, or drive
object.  It accepts explicit phase-to-phase P1 inputs and explicit count/peak-A
P2 inputs, then returns immutable candidate/response data.  Results are MODEL
evidence, not EAS parity and not hardware verification.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping

import numpy as np

import autotune_current
import autotune_velpos


PHASE_TO_PHASE = "phase-to-phase"
MODEL_STATUS = "MODEL"
ENCODER_COUNTS_PER_SECOND = "encoder-counts-per-second"
PEAK_AMPERES = "peak-amperes"
_MIN_RESPONSE_POINTS = 64
_MAX_RESPONSE_POINTS = 4096
_VP_TS_MIN_US = 40
_VP_TS_MAX_US = 120


def _finite_positive(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a finite positive number" % name)
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError("%s must be a finite positive number" % name)
    return number


def _finite_nonnegative(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a finite nonnegative number" % name)
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("%s must be a finite nonnegative number" % name)
    return number


def _require_close(actual: float, expected: float, name: str, *,
                   rel_tol=1e-9, abs_tol=1e-9) -> None:
    if not math.isclose(
            float(actual), float(expected),
            rel_tol=float(rel_tol), abs_tol=float(abs_tol)):
        raise ValueError("%s is not coherent with its source model" % name)


@dataclass(frozen=True)
class CurrentPlant:
    """Explicit phase-to-phase RL plant and controller sampling time."""

    resistance_ohm: float
    inductance_h: float
    sampling_time_s: float
    basis: str = PHASE_TO_PHASE

    def __post_init__(self):
        if self.basis != PHASE_TO_PHASE:
            raise ValueError(
                "Expert v1 accepts phase-to-phase resistance/inductance only")
        _finite_positive(self.resistance_ohm, "resistance_ohm")
        _finite_positive(self.inductance_h, "inductance_h")
        _finite_positive(self.sampling_time_s, "sampling_time_s")


@dataclass(frozen=True)
class CurrentCandidate:
    """One immutable offline PI candidate with modeled loop evidence."""

    kp_v_per_a: float
    ki_hz: float
    crossover_hz: float
    phase_margin_deg: float
    target_bandwidth_hz: float | None
    design_passed: bool
    source: str
    basis: str = PHASE_TO_PHASE
    model_status: str = MODEL_STATUS


@dataclass(frozen=True)
class CurrentFrequencyResponse:
    """Bounded chart-ready frequency response on one deterministic log grid."""

    frequency_hz: tuple[float, ...]
    plant_magnitude_db: tuple[float, ...]
    open_loop_magnitude_db: tuple[float, ...]
    open_loop_phase_deg: tuple[float, ...]
    closed_loop_magnitude_db: tuple[float, ...]


@dataclass(frozen=True)
class VelocityPositionPlant:
    """Explicit linear P2 model chained to one complete P1 MODEL candidate.

    Current is peak amperes and velocity is encoder counts per second.  No
    implicit RMS, rpm, user-unit, or phase-basis conversion is performed.
    """

    current_plant: CurrentPlant
    current_candidate: CurrentCandidate
    accel_constant_cnt_per_s2_per_a_peak: float
    viscous_friction_a_peak_per_cnt_s: float
    velocity_basis: str = ENCODER_COUNTS_PER_SECOND
    current_basis: str = PEAK_AMPERES

    def __post_init__(self):
        if not isinstance(self.current_plant, CurrentPlant):
            raise TypeError("current_plant must be CurrentPlant")
        if not isinstance(self.current_candidate, CurrentCandidate):
            raise TypeError("current_candidate must be CurrentCandidate")
        if self.velocity_basis != ENCODER_COUNTS_PER_SECOND:
            raise ValueError(
                "velocity_basis must be encoder-counts-per-second")
        if self.current_basis != PEAK_AMPERES:
            raise ValueError("current_basis must be peak-amperes")
        if self.current_candidate.basis != self.current_plant.basis:
            raise ValueError("current candidate and plant basis must match")
        if self.current_candidate.model_status != MODEL_STATUS:
            raise ValueError("P2 requires a current MODEL candidate")
        if self.current_candidate.design_passed is not True:
            raise ValueError("P2 requires a passing current MODEL candidate")
        for value, name in (
                (self.current_candidate.kp_v_per_a, "current KP"),
                (self.current_candidate.ki_hz, "current KI"),
                (self.current_candidate.crossover_hz,
                 "current crossover_hz"),
                (self.current_candidate.phase_margin_deg,
                 "current phase_margin_deg")):
            _finite_positive(value, name)
        k_a = _finite_positive(
            self.accel_constant_cnt_per_s2_per_a_peak,
            "accel_constant_cnt_per_s2_per_a_peak")
        ka_min, ka_max = autotune_velpos.KA_RANGE
        if not ka_min <= k_a <= ka_max:
            raise ValueError(
                "accel constant is outside MODEL range %.6g..%.6g"
                % (ka_min, ka_max))
        b_visc = _finite_nonnegative(
            self.viscous_friction_a_peak_per_cnt_s,
            "viscous_friction_a_peak_per_cnt_s")
        if not math.isfinite(k_a * b_visc):
            raise ValueError("K_a * B must be finite")

        # A matching basis string does not prove that this candidate was
        # calculated for this exact R/L/TS plant.  Recompute the P1 evidence
        # before allowing it to become the current-loop authority for P2.
        w_ci, phase_margin = autotune_current.loop_margins(
            float(self.current_candidate.kp_v_per_a),
            float(self.current_candidate.ki_hz),
            float(self.current_plant.resistance_ohm),
            float(self.current_plant.inductance_h),
            float(self.current_plant.sampling_time_s),
        )
        crossover_hz = float(w_ci) / (2.0 * math.pi)
        if not all(math.isfinite(value) for value in (
                w_ci, phase_margin, crossover_hz)):
            raise ValueError(
                "current candidate is not coherent with the current plant")
        try:
            _require_close(
                crossover_hz, self.current_candidate.crossover_hz,
                "current candidate crossover")
            _require_close(
                phase_margin, self.current_candidate.phase_margin_deg,
                "current candidate phase margin")
        except ValueError as exc:
            raise ValueError(
                "current candidate is not coherent with the current plant"
            ) from exc
        target_hz = self.current_candidate.target_bandwidth_hz
        target_gate = True
        if target_hz is not None:
            target_hz = _finite_positive(
                target_hz, "current target_bandwidth_hz")
            target_gate = (
                2.0 * math.pi * target_hz
                * float(self.current_plant.sampling_time_s)
                <= autotune_current.WCTS_MAX)
        current_gate = (
            phase_margin >= autotune_current.PM_MIN_DEG
            and 0.0 < self.current_candidate.kp_v_per_a
            <= autotune_current.KP_MAX
            and 0.0 < self.current_candidate.ki_hz
            <= autotune_current.KI_MAX
            and target_gate)
        if not current_gate:
            raise ValueError(
                "current candidate fails the exact current plant gate")


@dataclass(frozen=True)
class VelocityPositionCandidate:
    """Immutable P2 gain/margin projection; never installed-drive evidence."""

    kp_vel_a_per_cnt_s: float
    ki_vel_hz: float
    kp_pos_per_s: float
    d_visc_per_s: float
    design_bandwidth_rad_s: float
    current_crossover_hz: float
    current_phase_margin_deg: float
    velocity_crossover_hz: float
    velocity_phase_margin_deg: float
    velocity_gain_margin_db: float | None
    position_crossover_hz: float
    position_phase_margin_deg: float
    loop_model_passed: bool
    reductions: int
    current_source: str
    velocity_basis: str = ENCODER_COUNTS_PER_SECOND
    current_basis: str = PEAK_AMPERES
    model_status: str = MODEL_STATUS


def _validate_vp_sampling_time(sampling_time_s: float) -> None:
    ts_us = _finite_positive(sampling_time_s, "sampling_time_s") * 1e6
    nearest = int(round(ts_us))
    if (abs(ts_us - nearest) > 1e-9
            or nearest < _VP_TS_MIN_US
            or nearest > _VP_TS_MAX_US
            or nearest % 2):
        raise ValueError(
            "P2 MODEL TS must be an even integer in 40..120 us")


def _mapping_value(mapping: Mapping, key: str, *, positive=False) -> float:
    if key not in mapping:
        raise ValueError("P2 model result is missing %s" % key)
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("P2 model result %s is not numeric" % key)
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise ValueError("P2 model result %s is invalid" % key)
    return number


def design_velocity_position_candidate(
        plant: VelocityPositionPlant) -> VelocityPositionCandidate:
    """Design one zero-I/O P2 MODEL candidate from explicit P1/P2 inputs.

    The delegated kernel is the repository's existing, pure Phase-2 design
    law.  Its single-point calibration and bounded margin grid do not prove
    EAS parity, filter behavior, gain scheduling, or hardware stability.
    """
    if not isinstance(plant, VelocityPositionPlant):
        raise TypeError("plant must be VelocityPositionPlant")
    _validate_vp_sampling_time(plant.current_plant.sampling_time_s)
    k_a = float(plant.accel_constant_cnt_per_s2_per_a_peak)
    b_visc = float(plant.viscous_friction_a_peak_per_cnt_s)
    d_visc = k_a * b_visc
    params = autotune_velpos.AutotuneVPParams(
        r_pp_ohm=float(plant.current_plant.resistance_ohm),
        l_pp_h=float(plant.current_plant.inductance_h),
    )
    result = autotune_velpos.design_vp_gains(
        k_a,
        d_visc,
        float(plant.current_plant.sampling_time_s),
        params,
        float(plant.current_candidate.kp_v_per_a),
        float(plant.current_candidate.ki_hz),
    )
    if not isinstance(result, Mapping):
        raise ValueError("P2 model result must be a mapping")
    if not isinstance(result.get("ok"), bool):
        raise ValueError("P2 model result ok must be bool")
    iterations = result.get("iters")
    if (not isinstance(iterations, (tuple, list))
            or not 1 <= len(iterations) <= (
                1 + autotune_velpos.MAX_WCV_REDUCTIONS)):
        raise ValueError("P2 model iteration trace is missing or unbounded")
    if not all(
            isinstance(item, Mapping)
            and isinstance(item.get("pass"), bool)
            for item in iterations):
        raise ValueError("P2 model iteration trace is malformed")
    margins = result.get("margins")
    if not isinstance(margins, Mapping):
        raise ValueError("P2 model margins must be a mapping")

    kp2 = _mapping_value(result, "kp2", positive=True)
    ki2 = _mapping_value(result, "ki2", positive=True)
    kp3 = _mapping_value(result, "kp3", positive=True)
    wcv = _mapping_value(result, "wcv", positive=True)
    w_ci = _mapping_value(margins, "w_ci", positive=True)
    pm_i = _mapping_value(margins, "pm_i")
    w_cv = _mapping_value(margins, "w_cv", positive=True)
    pm_vel = _mapping_value(margins, "pm_vel")
    w_cp = _mapping_value(margins, "w_cp", positive=True)
    pm_pos = _mapping_value(margins, "pm_pos")
    gm_raw = margins.get("gm_db")
    if gm_raw is None:
        gm_db = None
    else:
        gm_db = _mapping_value(margins, "gm_db")

    reductions = len(iterations) - 1
    expected_wcv = (
        autotune_velpos.WCV_TS_CAL
        / float(plant.current_plant.sampling_time_s)
        * (0.8 ** reductions))
    _require_close(wcv, expected_wcv, "P2 design bandwidth")
    _require_close(kp2 * k_a, wcv, "P2 KP[2] gain law")
    _require_close(
        2.0 * math.pi * autotune_velpos.BETA_VEL * ki2,
        wcv, "P2 KI[2] gain law")
    _require_close(
        autotune_velpos.DELTA_POS * kp3,
        wcv, "P2 KP[3] gain law")

    # Recompute the final margins independently of design_vp_gains() so a
    # contradictory delegate ``ok``/trace cannot self-certify a P2 result.
    independent = autotune_velpos.vel_pos_margins(
        kp2,
        ki2,
        kp3,
        k_a,
        d_visc,
        float(plant.current_candidate.kp_v_per_a),
        float(plant.current_candidate.ki_hz),
        float(plant.current_plant.resistance_ohm),
        float(plant.current_plant.inductance_h),
        float(plant.current_plant.sampling_time_s),
    )
    if not isinstance(independent, Mapping):
        raise ValueError("independent P2 margins are malformed")
    verified_margins = {
        "w_ci": _mapping_value(independent, "w_ci", positive=True),
        "pm_i": _mapping_value(independent, "pm_i"),
        "w_cv": _mapping_value(independent, "w_cv", positive=True),
        "pm_vel": _mapping_value(independent, "pm_vel"),
        "w_cp": _mapping_value(independent, "w_cp", positive=True),
        "pm_pos": _mapping_value(independent, "pm_pos"),
    }
    independent_gm_raw = independent.get("gm_db")
    independent_gm = (
        None if independent_gm_raw is None
        else _mapping_value(independent, "gm_db"))
    delegated_margins = {
        "w_ci": w_ci,
        "pm_i": pm_i,
        "w_cv": w_cv,
        "pm_vel": pm_vel,
        "w_cp": w_cp,
        "pm_pos": pm_pos,
    }
    for key in ("w_ci", "w_cv", "w_cp"):
        _require_close(
            delegated_margins[key], verified_margins[key],
            "P2 margin %s" % key, rel_tol=5e-4, abs_tol=1e-9)
    for key in ("pm_i", "pm_vel", "pm_pos"):
        _require_close(
            delegated_margins[key], verified_margins[key],
            "P2 margin %s" % key, rel_tol=5e-4, abs_tol=0.05)
    if (gm_db is None) != (independent_gm is None):
        raise ValueError("P2 margin gm_db is not coherent with recomputation")
    if gm_db is not None:
        _require_close(
            gm_db, independent_gm, "P2 margin gm_db",
            rel_tol=5e-4, abs_tol=0.05)

    loop_model_passed = (
        verified_margins["pm_vel"] >= autotune_velpos.PM_VEL_MIN
        and (
            independent_gm is None
            or independent_gm >= autotune_velpos.GM_MIN_DB)
        and (
            wcv * float(plant.current_plant.sampling_time_s)
            <= autotune_velpos.WCV_TS_MAX)
        and verified_margins["pm_pos"] >= autotune_velpos.PM_POS_MIN
        and (
            verified_margins["w_ci"] / wcv
            >= autotune_velpos.RATIO_CI_CV_MIN)
        and (
            wcv / kp3
            >= autotune_velpos.RATIO_CV_KP3_MIN))
    if result["ok"] is not loop_model_passed:
        raise ValueError("P2 model gate contradicts recomputed margins")

    final_trace = iterations[-1]
    if final_trace["pass"] is not loop_model_passed:
        raise ValueError("P2 model trace gate contradicts final gate")
    for key, expected in (
            ("wcv_rad_s", wcv),
            ("kp2", kp2),
            ("ki2_hz", ki2),
            ("kp3", kp3),
            ("pm_vel", pm_vel),
            ("pm_pos", pm_pos),
            ("wcv_ts",
             wcv * float(plant.current_plant.sampling_time_s))):
        actual = _mapping_value(
            final_trace, key,
            positive=key in {
                "wcv_rad_s", "kp2", "ki2_hz", "kp3", "wcv_ts"})
        _require_close(
            actual, expected, "P2 final trace %s" % key,
            rel_tol=5e-4,
            abs_tol=0.05 if key.startswith("pm_") else 1e-9)
    trace_gm_raw = final_trace.get("gm_db")
    if (trace_gm_raw is None) != (gm_db is None):
        raise ValueError("P2 final trace gm_db is inconsistent")
    if gm_db is not None:
        trace_gm = _mapping_value(final_trace, "gm_db")
        _require_close(
            trace_gm, gm_db, "P2 final trace gm_db",
            rel_tol=5e-4, abs_tol=0.05)

    return VelocityPositionCandidate(
        kp_vel_a_per_cnt_s=kp2,
        ki_vel_hz=ki2,
        kp_pos_per_s=kp3,
        d_visc_per_s=d_visc,
        design_bandwidth_rad_s=wcv,
        current_crossover_hz=verified_margins["w_ci"] / (2.0 * math.pi),
        current_phase_margin_deg=verified_margins["pm_i"],
        velocity_crossover_hz=verified_margins["w_cv"] / (2.0 * math.pi),
        velocity_phase_margin_deg=verified_margins["pm_vel"],
        velocity_gain_margin_db=independent_gm,
        position_crossover_hz=verified_margins["w_cp"] / (2.0 * math.pi),
        position_phase_margin_deg=verified_margins["pm_pos"],
        loop_model_passed=loop_model_passed,
        reductions=reductions,
        current_source=str(plant.current_candidate.source),
    )


def _validate_candidate_numbers(kp_v_per_a, ki_hz) -> tuple[float, float]:
    return (
        _finite_positive(kp_v_per_a, "kp_v_per_a"),
        _finite_positive(ki_hz, "ki_hz"),
    )


def design_current_candidate(
        plant: CurrentPlant, *, target_bandwidth_hz: float | None = None,
        ki_rule: str = "eas_ratio") -> CurrentCandidate:
    """Design one candidate with the repository's existing bounded MODEL law."""
    if not isinstance(plant, CurrentPlant):
        raise TypeError("plant must be CurrentPlant")
    if target_bandwidth_hz is not None:
        target_bandwidth_hz = _finite_positive(
            target_bandwidth_hz, "target_bandwidth_hz")
    if ki_rule not in {"eas_ratio", "pole_zero"}:
        raise ValueError("ki_rule must be 'eas_ratio' or 'pole_zero'")
    params = autotune_current.AutotuneParams(
        wc_override_hz=target_bandwidth_hz,
        ki_rule=ki_rule,
    )
    ok, kp, ki, wc, pm, wx, _iterations = autotune_current.design_gains(
        float(plant.inductance_h),
        float(plant.resistance_ohm),
        float(plant.sampling_time_s),
        params,
    )
    return CurrentCandidate(
        kp_v_per_a=float(kp),
        ki_hz=float(ki),
        crossover_hz=float(wx) / (2.0 * math.pi),
        phase_margin_deg=float(pm),
        target_bandwidth_hz=float(wc) / (2.0 * math.pi),
        design_passed=bool(ok),
        source="AUTO_CALIBRATED_MODEL",
    )


def evaluate_manual_current_candidate(
        plant: CurrentPlant, *, kp_v_per_a: float,
        ki_hz: float) -> CurrentCandidate:
    """Evaluate manual PI numbers without applying them to a drive."""
    if not isinstance(plant, CurrentPlant):
        raise TypeError("plant must be CurrentPlant")
    kp, ki = _validate_candidate_numbers(kp_v_per_a, ki_hz)
    wx, pm = autotune_current.loop_margins(
        kp,
        ki,
        float(plant.resistance_ohm),
        float(plant.inductance_h),
        float(plant.sampling_time_s),
    )
    passed = bool(
        math.isfinite(pm)
        and pm >= autotune_current.PM_MIN_DEG
        and kp <= autotune_current.KP_MAX
        and ki <= autotune_current.KI_MAX
    )
    return CurrentCandidate(
        kp_v_per_a=kp,
        ki_hz=ki,
        crossover_hz=float(wx) / (2.0 * math.pi),
        phase_margin_deg=float(pm),
        target_bandwidth_hz=None,
        design_passed=passed,
        source="MANUAL",
    )


def _db(values: np.ndarray) -> np.ndarray:
    magnitudes = np.abs(values)
    if not np.all(np.isfinite(magnitudes)) or np.any(magnitudes <= 0.0):
        raise ValueError("frequency response contains invalid magnitude")
    return 20.0 * np.log10(magnitudes)


def current_frequency_response(
        plant: CurrentPlant, candidate: CurrentCandidate, *,
        f_min_hz: float = 10.0, f_max_hz: float | None = None,
        points: int = 401) -> CurrentFrequencyResponse:
    """Return a deterministic bounded plant/open/closed-loop Bode dataset."""
    if not isinstance(plant, CurrentPlant):
        raise TypeError("plant must be CurrentPlant")
    if not isinstance(candidate, CurrentCandidate):
        raise TypeError("candidate must be CurrentCandidate")
    if candidate.basis != plant.basis:
        raise ValueError("candidate and plant basis must match")
    f_min = _finite_positive(f_min_hz, "f_min_hz")
    if f_max_hz is None:
        f_max = min(20_000.0, 0.45 / float(plant.sampling_time_s))
    else:
        f_max = _finite_positive(f_max_hz, "f_max_hz")
    if f_max <= f_min:
        raise ValueError("f_max_hz must be greater than f_min_hz")
    if (isinstance(points, bool) or not isinstance(points, int)
            or not _MIN_RESPONSE_POINTS <= points <= _MAX_RESPONSE_POINTS):
        raise ValueError(
            "points must be an integer in %d..%d"
            % (_MIN_RESPONSE_POINTS, _MAX_RESPONSE_POINTS))

    frequency = np.logspace(
        math.log10(f_min), math.log10(f_max), int(points), dtype=float)
    omega = 2.0 * np.pi * frequency
    controller = (
        float(candidate.kp_v_per_a)
        * (1j * omega + 2.0 * np.pi * float(candidate.ki_hz))
        / (1j * omega)
    )
    plant_response = 1.0 / (
        float(plant.inductance_h) * 1j * omega
        + float(plant.resistance_ohm)
    )
    delay = np.exp(
        -1j * omega * autotune_current.DELAY_MULT
        * float(plant.sampling_time_s))
    open_loop = controller * plant_response * delay
    denominator = 1.0 + open_loop
    if (not np.all(np.isfinite(denominator))
            or np.any(np.abs(denominator) <= np.finfo(float).tiny)):
        raise ValueError("closed-loop response is singular on the requested grid")
    closed_loop = open_loop / denominator
    phase = np.degrees(np.unwrap(np.angle(open_loop)))

    series = (
        frequency,
        _db(plant_response),
        _db(open_loop),
        phase,
        _db(closed_loop),
    )
    if not all(np.all(np.isfinite(item)) for item in series):
        raise ValueError("frequency response contains non-finite values")
    return CurrentFrequencyResponse(
        frequency_hz=tuple(float(value) for value in frequency),
        plant_magnitude_db=tuple(float(value) for value in series[1]),
        open_loop_magnitude_db=tuple(float(value) for value in series[2]),
        open_loop_phase_deg=tuple(float(value) for value in series[3]),
        closed_loop_magnitude_db=tuple(float(value) for value in series[4]),
    )


__all__ = [
    "PHASE_TO_PHASE",
    "MODEL_STATUS",
    "ENCODER_COUNTS_PER_SECOND",
    "PEAK_AMPERES",
    "CurrentPlant",
    "CurrentCandidate",
    "CurrentFrequencyResponse",
    "VelocityPositionPlant",
    "VelocityPositionCandidate",
    "design_current_candidate",
    "evaluate_manual_current_candidate",
    "current_frequency_response",
    "design_velocity_position_candidate",
]
