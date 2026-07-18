"""Pure offline current-loop design model for Expert Candidate Lab v1.

This module intentionally owns no transport, worker, Qt, vendor-DLL, or drive
object.  It accepts explicit phase-to-phase SI inputs and returns immutable
candidate/response data.  Results are MODEL evidence, not EAS parity and not
hardware verification.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

import autotune_current


PHASE_TO_PHASE = "phase-to-phase"
MODEL_STATUS = "MODEL"
_MIN_RESPONSE_POINTS = 64
_MAX_RESPONSE_POINTS = 4096


def _finite_positive(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a finite positive number" % name)
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError("%s must be a finite positive number" % name)
    return number


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
    "CurrentPlant",
    "CurrentCandidate",
    "CurrentFrequencyResponse",
    "design_current_candidate",
    "evaluate_manual_current_candidate",
    "current_frequency_response",
]
