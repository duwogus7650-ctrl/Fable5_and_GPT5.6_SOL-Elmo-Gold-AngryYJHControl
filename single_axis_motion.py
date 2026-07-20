"""Bounded Single Axis Motion primitives for an Elmo Gold drive.

The public motion path is deliberately narrower than EAS III.  Version 1 only
performs a finite position move in UM=5 and always disables the drive after the
move.  Endless JV jogging, homing, torque/current and sine references remain
locked until their independent limit/watchdog contracts are available.

No function in this module sends ``SV``.  Temporary current/profile limits are
applied in RAM, independently read back, and restored after every exit path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any, Callable, Mapping, Optional

import single_axis_drive_mode


GREEN = "GREEN"
RED = "RED"
UNKNOWN = "UNKNOWN"

MAX_SPEED_RPM = 60.0
MAX_ACCEL_RPM_S = 600.0
MAX_STOP_DECEL_RPM_S = 600.0
MAX_TRAVEL_LIMIT_REV = 1.0
MAX_STEP_REV = 0.25
# 3.50 A peak session cap (drive clamps PL[1]=CL[1] to this). 1.30 A sat inside
# the static-friction band (i_ba 0.8-1.3 A) so the closed-loop enable/hold
# transient always saturated; 3.50 A clears 2x the 1.3 A signature ceiling with
# margin, matches this rig's sealed drag limit, and a stall at 3.50 A (2.5 Arms,
# 16% of the 15 Arms continuous rating) trips the I2t thermal guard in ~1 s.
MAX_CURRENT_CAP_A = 3.50
MIN_CURRENT_CAP_A = 0.10
SMOOTHING_MS = 20

# Active supervision uses a short per-command deadline and rejects a host-side
# multi-register sample if acquisition takes too long.  This is an application
# watchdog, not an independent STO or a coherent drive-side timestamp.
ACTIVE_READ_TIMEOUT_MS = 100
MAX_ACTIVE_SAMPLE_AGE_S = 0.25

# PE is DV[3]-PX in counts in UM=5.  A finite v1 move never accepts more than
# one percent of a mechanical revolution of tracking error (subject to the
# five-count quantization tolerance below), irrespective of requested travel.
MAX_POSITION_ERROR_REV = 0.01
PX_DIRECTION_TOLERANCE_REV = 0.0002

CURRENT_ZERO_TOLERANCE_A = 0.10
CURRENT_LIMIT_REL_MARGIN = 0.05
CURRENT_LIMIT_ABS_MARGIN_A = 0.02
CURRENT_CONVENTION = {
    "unit": "A",
    "components": "ID reactive / IQ active motor phase-current components",
    "magnitude": "sqrt(ID^2 + IQ^2)",
    "limit_basis": (
        "native drive ampere/amplitude convention; no RMS conversion"),
}

TEMPORARY_SETTING_ORDER = (
    "PL[1]", "CL[1]", "SP", "AC", "DC", "SD", "FS", "SF[1]", "SF[2]")
_APPLY_ORDER = (
    "CL[1]", "PL[1]", "SP", "AC", "DC", "SD", "FS", "SF[1]", "SF[2]")
_RESTORE_ORDER = (
    "SP", "AC", "DC", "SD", "FS", "SF[1]", "SF[2]", "PL[1]", "CL[1]")

# --- Endless JV jog (fable-physics motion-safety review 2026-07-20) --------------
# JV jog is an ENDLESS velocity motion that (per CR p175, command-reference.txt
# :9453) ignores the software position limits VH[3]/VL[3] and the modulo range,
# so the finite-move position-envelope guard gives ZERO protection here.  The
# endless mode is bounded instead by: a command-freshness deadman, a mandatory
# max-duration timebox, a ramp-aware overspeed guard with an absolute ceiling,
# the reused current-vector cap, and a two-tier stop chain.  JOG_MAX defaults
# conservative (rated 3600 rpm = the drive voltage-limit speed with zero torque
# margin, so continuous jog stays well below it) and is always re-clamped to the
# live VH[2] speed limit at runtime.
JOG_MAX_RPM_DEFAULT = 300.0        # 8.3% of rated; runaway trips in 1-2 polls
JOG_MAX_RPM_CEILING = 3000.0       # -17% of the 3600 rpm voltage limit
JOG_MIN_RPM = 1.0
JOG_ACCEL_RPM_S = 30.0
JOG_MAX_ACCEL_RPM_S = 600.0
JOG_POLL_S = 0.03                  # 30 ms tick (>=1-2 poll runaway detection)
JOG_DEADMAN_AGE_S = 0.25           # stale jog command -> demote to stop
JOG_TIMEBOX_DEFAULT_S = 60.0       # PX int32 headroom 0.92% at 300 rpm / 60 s
JOG_TIMEBOX_HARD_S = 180.0
JOG_OVERSPEED_FACTOR = 1.25
JOG_OVERSPEED_FLOOR_RPM = 15.0     # low-speed false-positive floor
JOG_STOP_SETTLE_TIMEOUT_S = 2.0    # operator stop: minimum |VX|~0 settle floor
JOG_STOP_SETTLE_TIMEOUT_S_MAX = 15.0  # cap on the decel-sized settle wait
JOG_STOP_RPM = 1.0                 # |VX| below this (rpm) counts as stopped
JOG_PROFILE_VELOCITY_MODE = 3      # OV[2] during a JV jog (CR :9450), not 1


@dataclass(frozen=True)
class JogRequest:
    """One endless JV jog session; the kernel always auto-disables on exit.

    ``max_speed_rpm`` is the per-session ceiling the operator may command in
    either direction; the live signed jog target is supplied per-tick by the
    command hook and clamped to +-this value (and to the live VH[2]).
    """

    max_speed_rpm: float = JOG_MAX_RPM_DEFAULT
    accel_rpm_s: float = JOG_ACCEL_RPM_S
    current_cap_a: float = 3.0
    timebox_s: float = JOG_TIMEBOX_DEFAULT_S


@dataclass(frozen=True)
class PositionMoveRequest:
    """One finite UM=5 position request expressed in session revolutions.

    ``relative`` adds ``target_rev`` to fresh PX. ``session_absolute`` targets
    ``target_rev`` from the current PX=0 session coordinate.  Both are confined
    to ``+-travel_limit_rev`` around that session zero.
    """

    mode: str
    target_rev: float
    speed_rpm: float = 5.0
    accel_rpm_s: float = 30.0
    travel_limit_rev: float = 0.25
    current_cap_a: float = 1.30


@dataclass
class MotionResult:
    status: str
    reason: str = ""
    target_counts: Optional[int] = None
    final_state: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


class _MotionRejected(RuntimeError):
    pass


class _MotionAborted(RuntimeError):
    pass


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise _MotionRejected("%s must be a finite number" % name)
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _MotionRejected("%s must be a finite number" % name) from exc
    if not math.isfinite(numeric):
        raise _MotionRejected("%s must be a finite number" % name)
    return numeric


def _number(response: Any, name: str) -> float:
    if response is None:
        raise _MotionRejected("%s readback is missing" % name)
    token = str(response).strip().rstrip(";").strip()
    try:
        value = float(token)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _MotionRejected("%s readback is not numeric: %r" % (name, response)) from exc
    if not math.isfinite(value):
        raise _MotionRejected("%s readback is not finite: %r" % (name, response))
    return value


def _read(link: Any, command: str, *, allow_motion: bool = False,
          timeout_ms: Optional[int] = None) -> float:
    # Bare PA/JV/PR queries do not move the axis, but ElmoLink deliberately
    # classifies their prefixes as motion-capable.  Carry the same supervised
    # authority used for the preceding write into that exact readback.
    kwargs: dict[str, Any] = {"allow_motion": allow_motion}
    if timeout_ms is not None:
        kwargs["timeout_ms"] = int(timeout_ms)
    return _number(link.command(command, **kwargs), command)


def _format_wire(value: float) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return "%.9g" % numeric


def _same_numeric(left: float, right: float) -> bool:
    scale = max(1.0, abs(float(left)), abs(float(right)))
    return abs(float(left) - float(right)) <= max(1e-9, 2e-6 * scale)


def _current_vector_a(id_a: float, iq_a: float) -> float:
    """Return native-drive current-vector magnitude in amperes.

    The Gold command reference defines ID and IQ as orthogonal reactive and
    active components of motor phase current, both in amperes.  PL[1]/CL[1]
    and ID/IQ are deliberately compared without an RMS conversion.
    """
    return math.hypot(float(id_a), float(iq_a))


# SR bit 13 (LC) is deliberately NOT here.  Per the Gold command reference
# (LC, p185) LC is a *selector* of which limit is presently dominant, not a
# saturation event: LC=0 => current limited by PL[1] (peak) or motor off;
# LC=1 => limited by CL[1] (continuous).  With the motor enabled one of the
# two is ALWAYS asserted, and run_jog writes PL[1]==CL[1]==cap, which removes
# the peak-budget window and pins LC=1 permanently regardless of the real
# current (measured 0.1 A against a 3 A cap on the bench).  Real over-current
# is caught by the current-vector guard (sqrt(ID^2+IQ^2) > cap+margin), not by
# this status bit.  EAS jogs the same drive with LC=1 continuously.
_UNSAFE_SR_MASK = (
    0xF | (1 << 6) | (1 << 7) | (1 << 12) | (1 << 28))


def _validate_enabled_state(sample: Mapping[str, float], context: str) -> None:
    if int(sample["MO"]) != 1 or int(sample["SO"]) != 1:
        raise _MotionAborted("enable feedback dropped %s" % context)
    if int(sample["MF"]) != 0:
        raise _MotionAborted(
            "drive fault %s (MF=%s)" % (context, sample["MF"]))
    if int(sample["PS"]) == 1:
        raise _MotionAborted("user program started %s (PS=1)" % context)
    sr = int(sample["SR"])
    if sr & _UNSAFE_SR_MASK:
        raise _MotionAborted("unsafe SR status %s (SR=%s)" % (context, sr))
    if not (sr & (1 << 14)) or not (sr & (1 << 15)):
        raise _MotionAborted("STO permission dropped %s" % context)
    if not (sr & (1 << 4)):
        raise _MotionAborted("SR motor-on feedback dropped %s" % context)


def _read_active_sample(
        link: Any,
        names: tuple[str, ...],
        *,
        sample_clock_fn: Callable[[], float],
) -> tuple[dict[str, float], float]:
    """Acquire one bounded host-side sample and return (values, age_s)."""
    started = _finite(sample_clock_fn(), "sample start time")
    values = {
        name: _read(link, name, timeout_ms=ACTIVE_READ_TIMEOUT_MS)
        for name in names
    }
    finished = _finite(sample_clock_fn(), "sample finish time")
    age_s = finished - started
    if age_s < 0:
        raise _MotionAborted("active sample clock regressed")
    if age_s > MAX_ACTIVE_SAMPLE_AGE_S:
        raise _MotionAborted(
            "active sample age %.3f s exceeds %.3f s host limit" %
            (age_s, MAX_ACTIVE_SAMPLE_AGE_S))
    return values, age_s


def _session_token(link: Any):
    getter = getattr(link, "transaction_session_identity", None)
    return getter() if callable(getter) else link


def _assert_same_session(link: Any, token: Any) -> None:
    observed = _session_token(link)
    if token is None or (observed is not token and observed != token):
        raise _MotionRejected("connection session changed during motion transaction")


def _persistence_unknown(link: Any) -> bool:
    getter = getattr(link, "persistence_unknown_latched", None)
    return bool(getter()) if callable(getter) else False


def _write_verified(link: Any, command: str, value: float, token: Any,
                    *, allow_motion: bool = False) -> None:
    _assert_same_session(link, token)
    wire = _format_wire(value)
    link.command("%s=%s" % (command, wire), allow_motion=allow_motion)
    _assert_same_session(link, token)
    observed = _read(link, command, allow_motion=allow_motion)
    if not _same_numeric(observed, value):
        raise _MotionRejected(
            "%s readback mismatch: wrote %s, observed %s" %
            (command, wire, _format_wire(observed)))


def _validate_request(request: PositionMoveRequest) -> dict[str, float | str]:
    if not isinstance(request, PositionMoveRequest):
        raise _MotionRejected("structured PositionMoveRequest is required")
    if request.mode not in ("relative", "session_absolute"):
        raise _MotionRejected("mode must be relative or session_absolute")
    target_rev = _finite(request.target_rev, "target_rev")
    speed_rpm = _finite(request.speed_rpm, "speed_rpm")
    accel_rpm_s = _finite(request.accel_rpm_s, "accel_rpm_s")
    travel_limit_rev = _finite(request.travel_limit_rev, "travel_limit_rev")
    current_cap_a = _finite(request.current_cap_a, "current_cap_a")
    if not 0.0 < speed_rpm <= MAX_SPEED_RPM:
        raise _MotionRejected("speed_rpm must be >0 and <= %.1f" % MAX_SPEED_RPM)
    if not 0.0 < accel_rpm_s <= MAX_ACCEL_RPM_S:
        raise _MotionRejected(
            "accel_rpm_s must be >0 and <= %.1f" % MAX_ACCEL_RPM_S)
    if not 0.0 < travel_limit_rev <= MAX_TRAVEL_LIMIT_REV:
        raise _MotionRejected(
            "travel_limit_rev must be >0 and <= %.1f" % MAX_TRAVEL_LIMIT_REV)
    if abs(target_rev) > MAX_STEP_REV and request.mode == "relative":
        raise _MotionRejected(
            "relative step exceeds hard limit %.3f rev" % MAX_STEP_REV)
    if not MIN_CURRENT_CAP_A <= current_cap_a <= MAX_CURRENT_CAP_A:
        raise _MotionRejected(
            "current_cap_a must be %.2f..%.2f A" %
            (MIN_CURRENT_CAP_A, MAX_CURRENT_CAP_A))
    return {
        "mode": request.mode,
        "target_rev": target_rev,
        "speed_rpm": speed_rpm,
        "accel_rpm_s": accel_rpm_s,
        "travel_limit_rev": travel_limit_rev,
        "current_cap_a": current_cap_a,
    }


_AXIS_READS = (
    "UM", "RM", "MO", "SO", "MF", "PS", "SR", "PX", "VX", "PE", "ID", "IQ", "MS",
    "CA[18]", "CA[28]", "CA[41]", "CA[45]", "CA[46]", "CA[47]",
    "CA[54]", "CA[55]", "CA[56]", "CA[57]",
    *("FC[%d]" % index for index in range(1, 13)),
    "BP[1]", "BP[2]", "SC[13]",
    "VL[3]", "VH[3]", "XM[1]", "XM[2]", "VH[2]",
    "SP", "AC", "DC", "SD", "FS", "SF[1]", "SF[2]", "PL[1]", "CL[1]",
)


def read_axis_summary(link: Any) -> dict[str, Any]:
    """Read a Quick-Tuning Axis summary without writing or inventing EAS IDs."""
    raw: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for command in _AXIS_READS:
        try:
            value = _read(link, command)
            raw[command] = int(value) if value.is_integer() else value
        except Exception as exc:
            raw[command] = None
            errors[command] = str(exc)

    um = raw.get("UM")
    mode_spec = None
    if (isinstance(um, (int, float))
            and not isinstance(um, bool)
            and math.isfinite(float(um))
            and float(um).is_integer()):
        mode_spec = single_axis_drive_mode.MODE_SPECS.get(int(um))
    mode = (
        "%s (UM=%d)" % (mode_spec.name, mode_spec.value)
        if mode_spec is not None
        else "Unknown (UM=%r)" % um
    )
    pos_socket, vel_socket = raw.get("CA[45]"), raw.get("CA[46]")
    if (isinstance(pos_socket, (int, float)) and
            isinstance(vel_socket, (int, float)) and pos_socket == vel_socket):
        routing = "same socket routing (%d)" % int(pos_socket)
    else:
        routing = "position=%r / velocity=%r" % (pos_socket, vel_socket)
    return {
        "scope": "Single Axis (application scope)",
        "mode": mode,
        "feedback_routing": routing,
        "gear_ratio_raw": {
            "motor_shaft": raw.get("FC[5]"),
            "driving_shaft": raw.get("FC[6]"),
        },
        "raw": raw,
        "errors": errors,
        "write_supported": False,
        "write_reason": (
            "read-only v1: Axis writes require Preview/RAM/readback/rollback/explicit SV"),
    }


def _preflight(link: Any, values: Mapping[str, Any], *,
               require_target: bool = True) -> dict[str, float]:
    names = (
        "UM", "RM", "MO", "SO", "MF", "PS", "SR", "PX", "VX", "PE", "ID", "IQ", "MS",
        "CA[18]", "VH[2]", "VL[3]", "VH[3]", "XM[1]", "XM[2]",
        *TEMPORARY_SETTING_ORDER,
        *("FC[%d]" % index for index in range(1, 13)),
    )
    state = {name: _read(link, name) for name in names}
    if int(state["UM"]) != 5:
        raise _MotionRejected("finite position motion requires UM=5")
    if int(state["RM"]) != 0:
        raise _MotionRejected("external reference must be disabled (RM=0)")
    if int(state["MO"]) != 0 or int(state["SO"]) != 0:
        raise _MotionRejected("entry requires MO=0 and SO=0; use STOP + Disable first")
    if int(state["MS"]) != 3:
        raise _MotionRejected("disabled entry requires MS=3 (no active profiler)")
    if int(state["MF"]) != 0:
        raise _MotionRejected("drive fault must be clear (MF=0)")
    if int(state["PS"]) == 1:
        raise _MotionRejected("user program is running (PS=1)")
    sr = int(state["SR"])
    if not (sr & (1 << 14)) or not (sr & (1 << 15)):
        raise _MotionRejected("both STO status inputs must permit enable (SR bits 14/15)")
    if sr & _UNSAFE_SR_MASK:
        raise _MotionRejected(
            "drive status is not clear (SR bits 0..3/6/7/12/28)")
    ca18 = state["CA[18]"]
    if ca18 <= 0:
        raise _MotionRejected("CA[18] counts/rev must be positive")
    idle_speed = ca18 / 60.0
    if abs(state["VX"]) > idle_speed:
        raise _MotionRejected("axis is not stationary (|VX| > 1 rpm)")
    entry_current_a = _current_vector_a(state["ID"], state["IQ"])
    if entry_current_a > CURRENT_ZERO_TOLERANCE_A:
        raise _MotionRejected(
            "entry current vector is not near zero "
            "(sqrt(ID^2+IQ^2)=%.3f A > %.2f A)" %
            (entry_current_a, CURRENT_ZERO_TOLERANCE_A))
    non_unity = [name for name in state if name.startswith("FC[")
                 and not _same_numeric(state[name], 1.0)]
    if non_unity:
        raise _MotionRejected(
            "FC scaling is not unity (%s); v1 cannot prove rev/count conversion" %
            ", ".join(non_unity))
    if require_target:
        # Software position limits (VL[3]/VH[3]) and modulo bound a FINITE PA move.
        # An endless JV jog ignores VH[3]/VL[3] at the drive (CR p175), so these
        # checks — and the PA target computation — apply only to a position move,
        # never to a jog (which calls with require_target=False).
        vl, vh, xm1, xm2 = (state["VL[3]"], state["VH[3]"],
                             state["XM[1]"], state["XM[2]"])
        if not vl < vh:
            raise _MotionRejected("drive position limits are invalid (VL[3] < VH[3] required)")
        if vl == vh == xm1 == xm2 == 0:
            raise _MotionRejected("32-bit modulo/no-limit mode is not supported")
        non_modulo = ((xm1 == 0 and xm2 == 0) or (xm1 <= vl and xm2 >= vh))
        if not non_modulo:
            raise _MotionRejected("position modulo mode is not supported by finite-motion v1")
        target_counts = _target_from_px(state["PX"], values, state)
    requested_speed_counts = values["speed_rpm"] * ca18 / 60.0
    if state["VH[2]"] <= 0 or requested_speed_counts > state["VH[2]"]:
        raise _MotionRejected("requested speed exceeds drive VH[2] limit")
    if state["SD"] <= 0:
        raise _MotionRejected("existing SD stop deceleration is invalid")
    if require_target:
        state["target_counts"] = float(target_counts)
    state["ca18"] = ca18
    return state


def _target_from_px(current_px: float, values: Mapping[str, Any],
                    state: Mapping[str, float]) -> int:
    """Compute and validate a PA target from one fresh PX sample."""
    ca18 = state["CA[18]"] if "CA[18]" in state else state["ca18"]
    delta = values["target_rev"] * ca18
    target = current_px + delta if values["mode"] == "relative" else delta
    if abs(target - current_px) > MAX_STEP_REV * ca18:
        raise _MotionRejected(
            "resolved move exceeds hard limit %.3f rev" % MAX_STEP_REV)
    target_counts = int(round(target))
    envelope = values["travel_limit_rev"] * ca18
    if abs(current_px) > envelope:
        raise _MotionRejected(
            "current PX is outside the session envelope; Set Session Zero first")
    if abs(target_counts) > envelope:
        raise _MotionRejected("target is outside the configured session envelope")
    if target_counts < state["VL[3]"] or target_counts > state["VH[3]"]:
        raise _MotionRejected("target is outside drive VL[3]/VH[3] limits")
    if target_counts < -(2 ** 31) or target_counts > (2 ** 31 - 1):
        raise _MotionRejected("target exceeds signed 32-bit PA range")
    return target_counts


_MOTION_SAMPLE_READS = (
    "PX", "VX", "PE", "ID", "IQ", "MO", "SO", "MF", "PS", "MS",
    "DV[3]", "SR", "OV[2]",
)


def _read_motion_sample(
        link: Any, *, sample_clock_fn: Callable[[], float],
) -> tuple[dict[str, float], float]:
    return _read_active_sample(
        link, _MOTION_SAMPLE_READS, sample_clock_fn=sample_clock_fn)


def _restore_settings(link: Any, originals: Mapping[str, float], token: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for name in _RESTORE_ORDER:
        try:
            _write_verified(link, name, originals[name], token)
        except Exception as exc:
            errors.append("%s: %s" % (name, exc))
    return not errors, errors


def safe_stop_disable(link: Any, *, sleep_fn: Callable[[float], None] = time.sleep,
                      clock_fn: Callable[[], float] = time.monotonic,
                      timeout_s: float = 1.5) -> MotionResult:
    """Issue ST then MO=0 and verify drive torque disable.

    This path intentionally remains usable when persistence is UNKNOWN.  It
    proves MO/SO disable only; it does not claim the mechanics are stationary.
    """
    errors: list[str] = []
    try:
        link.command("ST")
    except Exception as exc:
        errors.append("ST: %s" % exc)
    try:
        link.command("MO=0")
    except Exception as exc:
        errors.append("MO=0: %s" % exc)
    deadline = clock_fn() + max(0.0, float(timeout_s))
    final: dict[str, Any] = {}
    while True:
        try:
            final["MO"] = _read(
                link, "MO", timeout_ms=ACTIVE_READ_TIMEOUT_MS)
            final["SO"] = _read(
                link, "SO", timeout_ms=ACTIVE_READ_TIMEOUT_MS)
            final["MS"] = _read(
                link, "MS", timeout_ms=ACTIVE_READ_TIMEOUT_MS)
            final["ID"] = _read(
                link, "ID", timeout_ms=ACTIVE_READ_TIMEOUT_MS)
            final["IQ"] = _read(
                link, "IQ", timeout_ms=ACTIVE_READ_TIMEOUT_MS)
            final["VX"] = _read(
                link, "VX", timeout_ms=ACTIVE_READ_TIMEOUT_MS)
            final["current_vector_a"] = _current_vector_a(
                final["ID"], final["IQ"])
            final["disabled_verified"] = (
                int(final["MO"]) == 0
                and int(final["SO"]) == 0
                and int(final["MS"]) == 3
                and final["current_vector_a"] <= CURRENT_ZERO_TOLERANCE_A)
            if final["disabled_verified"]:
                return MotionResult(
                    GREEN,
                    "MO=0/SO=0 verified; mechanical stop is not independently proven",
                    final_state=final,
                    evidence={"command_errors": errors})
        except Exception as exc:
            errors.append("final readback: %s" % exc)
        if clock_fn() >= deadline:
            final["disabled_verified"] = False
            return MotionResult(
                UNKNOWN,
                "STOP/disable final state could not be verified",
                final_state=final,
                evidence={"command_errors": errors})
        sleep_fn(0.02)


def run_position_move(
        link: Any,
        request: PositionMoveRequest,
        *,
        signature_green: bool,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        cancel_fn: Callable[[], bool] = lambda: False,
        sample_clock_fn: Callable[[], float] = time.monotonic,
) -> MotionResult:
    """Execute one bounded PTP move and always auto-disable/restore on exit."""
    evidence: dict[str, Any] = {
        "temporary_ram_only": True,
        "sv_sent": False,
        "settings_restored": None,
        "current_convention": dict(CURRENT_CONVENTION),
        "active_sample_contract": {
            "per_register_timeout_ms": ACTIVE_READ_TIMEOUT_MS,
            "max_host_acquisition_age_s": MAX_ACTIVE_SAMPLE_AGE_S,
            "drive_timestamp_available": False,
        },
    }
    target_counts: Optional[int] = None
    try:
        if cancel_fn():
            raise _MotionRejected("STOP/cancel request superseded motion before I/O")
        values = _validate_request(request)
        if not signature_green:
            raise _MotionRejected(
                "session commutation signature is not GREEN")
        if _persistence_unknown(link):
            raise _MotionRejected("persistence state UNKNOWN blocks enable/motion")
        token = _session_token(link)
        if token is None:
            raise _MotionRejected("live connection session identity is unavailable")
        state = _preflight(link, values)
        if cancel_fn():
            raise _MotionRejected("STOP/cancel request during preflight sample")
        target_counts = int(state["target_counts"])
    except Exception as exc:
        return MotionResult(RED, str(exc), target_counts=target_counts,
                            evidence=evidence)

    originals = {name: state[name] for name in TEMPORARY_SETTING_ORDER}
    cap = min(values["current_cap_a"], originals["PL[1]"], originals["CL[1]"])
    if cap < MIN_CURRENT_CAP_A:
        return MotionResult(
            RED, "existing PL[1]/CL[1] is below the supported current floor",
            target_counts=target_counts, evidence=evidence)
    speed_counts = max(1, int(round(values["speed_rpm"] * state["ca18"] / 60.0)))
    accel_counts = max(10, int(round(values["accel_rpm_s"] * state["ca18"] / 60.0)))
    stop_decel_rpm_s = min(values["accel_rpm_s"], MAX_STOP_DECEL_RPM_S)
    stop_decel_counts = max(
        100, int(round(stop_decel_rpm_s * state["ca18"] / 60.0)))
    if speed_counts > 2_000_000_000:
        return MotionResult(
            RED, "SP exceeds drive numeric range", target_counts=target_counts,
            evidence=evidence)
    if accel_counts > 2_000_000_000 or stop_decel_counts > 2_000_000_000:
        return MotionResult(
            RED, "AC/DC/SD exceeds drive numeric range",
            target_counts=target_counts, evidence=evidence)
    applied = {
        "PL[1]": cap,
        "CL[1]": cap,
        "SP": speed_counts,
        "AC": accel_counts,
        "DC": accel_counts,
        # ST uses SD.  Lower it to the same bounded, read-back acceleration
        # before enable so an unknown/high persistent SD cannot cause a harsher
        # software stop than this transaction requested.
        "SD": stop_decel_counts,
        # Explicitly zero FS: nonzero FS continues jogging after PA target.
        # Re-issue both SF array entries on every move because target firmware
        # 01.01.16.00 B01 has the documented power-up SF activation defect.
        "FS": 0,
        "SF[1]": SMOOTHING_MS,
        "SF[2]": 0,
    }
    evidence.update({
        "original_settings": dict(originals),
        "applied_settings": dict(applied),
        "session_token_present": True,
    })

    motion_started = False
    reason = ""
    operation_status = GREEN
    sample: dict[str, Any] = {}
    try:
        for name in _APPLY_ORDER:
            if cancel_fn():
                raise _MotionAborted("operator cancel while preparing RAM profile")
            _write_verified(link, name, applied[name], token)
        if not (applied["AC"] <= applied["SD"] and applied["DC"] <= applied["SD"]):
            raise _MotionAborted("profile invariant AC/DC <= SD was not satisfied")
        if cancel_fn():
            raise _MotionAborted("operator cancel before enable")
        _assert_same_session(link, token)
        link.command("MO=1", allow_motion=True)
        enable_deadline = clock_fn() + 1.5
        max_observed_sample_age_s = 0.0
        while True:
            enable_sample, sample_age_s = _read_active_sample(
                link, ("MO", "SO", "MF", "PS", "SR", "VX", "ID", "IQ"),
                sample_clock_fn=sample_clock_fn)
            max_observed_sample_age_s = max(
                max_observed_sample_age_s, sample_age_s)
            if cancel_fn():
                raise _MotionAborted("operator cancel during enable sample")
            sr = int(enable_sample["SR"])
            if int(enable_sample["MF"]) != 0:
                raise _MotionAborted("drive fault while enabling")
            if int(enable_sample["PS"]) == 1:
                raise _MotionAborted("user program started while enabling (PS=1)")
            if sr & _UNSAFE_SR_MASK:
                raise _MotionAborted(
                    "unsafe SR status while enabling (SR=%s)" % sr)
            if not (sr & (1 << 14)) or not (sr & (1 << 15)):
                raise _MotionAborted("STO permission dropped while enabling")
            enable_current_a = _current_vector_a(
                enable_sample["ID"], enable_sample["IQ"])
            if (abs(enable_sample["VX"]) > state["ca18"] / 60.0
                    or enable_current_a > (
                        cap * (1.0 + CURRENT_LIMIT_REL_MARGIN)
                        + CURRENT_LIMIT_ABS_MARGIN_A)):
                raise _MotionAborted("unintended motion/current while enabling")
            if (int(enable_sample["MO"]) == 1
                    and int(enable_sample["SO"]) == 1
                    and bool(sr & (1 << 4))):
                break
            if clock_fn() >= enable_deadline:
                raise _MotionAborted("MO=1 issued but SO=1 was not observed")
            sleep_fn(0.02)

        # PA-relative means relative to a fresh position, not the MO=0 sample
        # taken before profile writes and enable.  Recompute and revalidate here.
        enabled_px = _read(link, "PX")
        target_counts = _target_from_px(enabled_px, values, state)
        evidence["enabled_px"] = enabled_px
        evidence["resolved_target_counts"] = target_counts
        if cancel_fn():
            raise _MotionAborted("operator cancel before position command")
        _write_verified(link, "PA", target_counts, token, allow_motion=True)
        if cancel_fn():
            raise _MotionAborted("operator cancel after PA; BG not sent")
        # Last-moment exact profile and live-state proof.  In particular, FS
        # must still be 0; a nonzero FS turns a finite PA into continued
        # jogging after target.  MO/SO/MF/PS/SR are sampled again here because
        # the earlier enable sample is stale authority for BG.
        profile_names = (
            "SP", "AC", "DC", "SD", "FS", "SF[1]", "SF[2]",
            "PL[1]", "CL[1]",
        )
        bg_sample, sample_age_s = _read_active_sample(
            link,
            profile_names + ("MO", "SO", "MF", "PS", "SR"),
            sample_clock_fn=sample_clock_fn)
        max_observed_sample_age_s = max(
            max_observed_sample_age_s, sample_age_s)
        if cancel_fn():
            raise _MotionAborted("operator cancel during BG-preflight sample")
        for name in profile_names:
            if not _same_numeric(bg_sample[name], applied[name]):
                raise _MotionAborted("%s changed before BG" % name)
        _validate_enabled_state(bg_sample, "before BG")
        if cancel_fn():
            raise _MotionAborted("operator cancel before Begin Motion")
        _assert_same_session(link, token)
        link.command("BG", allow_motion=True)
        motion_started = True

        start_px = enabled_px
        distance = abs(target_counts - start_px)
        expected_s = distance / max(float(speed_counts), 1.0)
        deadline = clock_fn() + min(15.0, max(2.0, expected_s * 3.0 + 2.0))
        envelope = values["travel_limit_rev"] * state["ca18"]
        pos_tolerance = max(5.0, state["ca18"] * 0.001)
        direction_tolerance = max(
            2.0, state["ca18"] * PX_DIRECTION_TOLERANCE_REV)
        velocity_limit = speed_counts * 1.25 + state["ca18"] / 60.0
        tracking_limit = max(
            pos_tolerance,
            min(state["ca18"] * MAX_POSITION_ERROR_REV,
                distance + pos_tolerance))
        evidence["tracking_error_limit_counts"] = tracking_limit
        evidence["px_direction_tolerance_counts"] = direction_tolerance
        previous_demand = start_px
        previous_px = start_px
        demand_low = min(start_px, target_counts) - pos_tolerance
        demand_high = max(start_px, target_counts) + pos_tolerance
        actual_low = min(start_px, target_counts) - pos_tolerance
        actual_high = max(start_px, target_counts) + pos_tolerance
        while True:
            if cancel_fn():
                raise _MotionAborted("operator cancel after Begin Motion")
            sample, sample_age_s = _read_motion_sample(
                link, sample_clock_fn=sample_clock_fn)
            max_observed_sample_age_s = max(
                max_observed_sample_age_s, sample_age_s)
            # A cancel arriving while the sequential register sample was in
            # flight must supersede even an otherwise at-target sample.
            if cancel_fn():
                raise _MotionAborted("operator cancel during motion sample")
            _validate_enabled_state(sample, "during motion")
            if int(sample["OV[2]"]) != 1:
                raise _MotionAborted(
                    "actual motion mode OV[2] is not position mode (1)")
            current_vector_a = _current_vector_a(sample["ID"], sample["IQ"])
            if current_vector_a > (
                    cap * (1.0 + CURRENT_LIMIT_REL_MARGIN)
                    + CURRENT_LIMIT_ABS_MARGIN_A):
                raise _MotionAborted(
                    "current vector exceeded bounded move cap "
                    "(sqrt(ID^2+IQ^2)=%.3f A, ID=%.3f A, IQ=%.3f A, "
                    "cap=%.3f A; native drive amperes)" %
                    (current_vector_a, sample["ID"], sample["IQ"], cap))
            if abs(sample["VX"]) > velocity_limit:
                raise _MotionAborted("velocity exceeded bounded move limit")
            if abs(sample["PX"]) > envelope + pos_tolerance:
                raise _MotionAborted("PX left the session travel envelope")
            px = sample["PX"]
            if target_counts > start_px:
                if px < start_px - direction_tolerance:
                    raise _MotionAborted(
                        "actual PX moved in wrong direction for positive target")
                if px < previous_px - direction_tolerance:
                    raise _MotionAborted(
                        "actual PX became nonmonotonic during positive move")
            elif target_counts < start_px:
                if px > start_px + direction_tolerance:
                    raise _MotionAborted(
                        "actual PX moved in wrong direction for negative target")
                if px > previous_px + direction_tolerance:
                    raise _MotionAborted(
                        "actual PX became nonmonotonic during negative move")
            if px < actual_low or px > actual_high:
                raise _MotionAborted(
                    "actual PX left the finite start/target interval")
            previous_px = px
            if abs(sample["PE"]) > tracking_limit:
                raise _MotionAborted("position tracking error exceeded v1 limit")
            demand = sample["DV[3]"]
            if demand < demand_low or demand > demand_high:
                raise _MotionAborted("position demand DV[3] left the finite target interval")
            if (target_counts > start_px
                    and demand + pos_tolerance < previous_demand):
                raise _MotionAborted("position demand DV[3] reversed during positive ramp")
            if (target_counts < start_px
                    and demand - pos_tolerance > previous_demand):
                raise _MotionAborted("position demand DV[3] reversed during negative ramp")
            previous_demand = demand
            if int(sample["MS"]) == 0 and not _same_numeric(demand, target_counts):
                raise _MotionAborted(
                    "settled position demand DV[3] does not match target")
            at_target = (int(sample["MS"]) == 0
                         and abs(sample["PX"] - target_counts) <= pos_tolerance
                         and abs(sample["VX"]) <= state["ca18"] / 60.0)
            if at_target:
                if cancel_fn():
                    raise _MotionAborted(
                        "operator cancel before target completion verdict")
                break
            if clock_fn() >= deadline:
                raise _MotionAborted("finite move timed out")
            sleep_fn(0.02)
        if cancel_fn():
            raise _MotionAborted("operator cancel before GREEN verdict")
        reason = "finite PTP target reached"
    except Exception as exc:
        operation_status = RED
        reason = str(exc)

    stop_result = safe_stop_disable(
        link, sleep_fn=sleep_fn, clock_fn=clock_fn)
    # Never raise PL/CL/profile values while torque-disable is unverified.
    # Keeping the lower temporary caps and FS=0 is the safer UNKNOWN state.
    if stop_result.status == GREEN:
        restored, restore_errors = _restore_settings(link, originals, token)
    else:
        restored = False
        restore_errors = [
            "restore intentionally skipped: MO=0/SO=0 was not verified"]
    evidence["settings_restored"] = restored
    evidence["restore_errors"] = restore_errors
    evidence["motion_started"] = motion_started
    evidence["last_sample"] = sample
    evidence["stop_status"] = stop_result.status
    evidence["max_observed_active_sample_age_s"] = locals().get(
        "max_observed_sample_age_s")
    if stop_result.status != GREEN or not restored:
        operation_status = UNKNOWN
        details = []
        if stop_result.status != GREEN:
            details.append("MO/SO final disable unverified")
        if not restored:
            details.append("temporary setting restore failed")
        reason = (reason + "; " if reason else "") + "; ".join(details)
    if operation_status == GREEN and cancel_fn():
        operation_status = RED
        reason = "operator cancel during finalization; drive is disabled"
    return MotionResult(
        operation_status,
        reason,
        target_counts=target_counts,
        final_state=stop_result.final_state,
        evidence=evidence,
    )


def _validate_jog_request(request: JogRequest) -> dict[str, float]:
    max_speed = _finite(request.max_speed_rpm, "max_speed_rpm")
    accel = _finite(request.accel_rpm_s, "accel_rpm_s")
    current_cap = _finite(request.current_cap_a, "current_cap_a")
    timebox = _finite(request.timebox_s, "timebox_s")
    if not JOG_MIN_RPM <= max_speed <= JOG_MAX_RPM_CEILING:
        raise _MotionRejected(
            "max_speed_rpm must be in [%.1f, %.1f]"
            % (JOG_MIN_RPM, JOG_MAX_RPM_CEILING))
    if not 0.0 < accel <= JOG_MAX_ACCEL_RPM_S:
        raise _MotionRejected(
            "accel_rpm_s must be >0 and <= %.1f" % JOG_MAX_ACCEL_RPM_S)
    if not MIN_CURRENT_CAP_A <= current_cap <= MAX_CURRENT_CAP_A:
        raise _MotionRejected(
            "current_cap_a must be in [%.2f, %.2f]"
            % (MIN_CURRENT_CAP_A, MAX_CURRENT_CAP_A))
    if not 0.0 < timebox <= JOG_TIMEBOX_HARD_S:
        raise _MotionRejected(
            "timebox_s must be >0 and <= %.1f" % JOG_TIMEBOX_HARD_S)
    return {"speed_rpm": max_speed, "accel_rpm_s": accel,
            "current_cap_a": current_cap, "timebox_s": timebox}


_JOG_SAMPLE_READS = (
    "VX", "MF", "PS", "SR", "ID", "IQ", "OV[2]", "MO", "SO", "MS")


def run_jog(
        link: Any,
        request: JogRequest,
        *,
        signature_green: bool,
        jog_cmd_fn: Callable[[], Mapping[str, Any]],
        emit_fn: Optional[Callable[[Mapping[str, Any]], None]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        cancel_fn: Callable[[], bool] = lambda: False,
        sample_clock_fn: Callable[[], float] = time.monotonic,
) -> MotionResult:
    """Endless JV jog under host supervision; always auto-disable and restore.

    ``jog_cmd_fn()`` returns a mapping ``{"rpm": signed float, "stop": bool,
    "ts": monotonic timestamp}``.  The signed rpm is the live jog target
    (+/- for the two directions), clamped to +-``request.max_speed_rpm`` and to
    the live VH[2].  A command older than ``JOG_DEADMAN_AGE_S`` (host stalled)
    is demoted to stop -- this deadman replaces the finite move's PX envelope,
    since a JV jog is endless and ignores VH[3]/VL[3] (CR p175).  Guard set per
    the 2026-07-20 fable-physics motion-safety review.
    """
    evidence: dict[str, Any] = {
        "temporary_ram_only": True,
        "sv_sent": False,
        "settings_restored": None,
        "current_convention": dict(CURRENT_CONVENTION),
    }
    try:
        if cancel_fn():
            raise _MotionRejected("STOP/cancel superseded jog before I/O")
        values = _validate_jog_request(request)
        if not signature_green:
            raise _MotionRejected("session commutation signature is not GREEN")
        if _persistence_unknown(link):
            raise _MotionRejected("persistence state UNKNOWN blocks enable/motion")
        token = _session_token(link)
        if token is None:
            raise _MotionRejected("live connection session identity is unavailable")
        state = _preflight(link, values, require_target=False)
        if cancel_fn():
            raise _MotionRejected("STOP/cancel request during preflight sample")
    except Exception as exc:
        return MotionResult(RED, str(exc), evidence=evidence)

    ca18 = state["ca18"]
    idle_speed = ca18 / 60.0
    max_counts_per_s = values["speed_rpm"] * ca18 / 60.0
    # PX must not risk signed-32-bit overflow across the whole timebox (jog is
    # endless and does not stop at software limits).
    projected = abs(state["PX"]) + max_counts_per_s * values["timebox_s"]
    if projected >= 0.5 * (2 ** 31):
        return MotionResult(
            RED, "jog max-speed x timebox risks PX int32 overflow; reduce "
            "speed/timebox or Set Session Zero first", evidence=evidence)

    originals = {name: state[name] for name in TEMPORARY_SETTING_ORDER}
    cap = min(values["current_cap_a"], originals["PL[1]"], originals["CL[1]"])
    if cap < MIN_CURRENT_CAP_A:
        return MotionResult(
            RED, "existing PL[1]/CL[1] is below the supported current floor",
            evidence=evidence)
    speed_counts = max(1, int(round(max_counts_per_s)))
    accel_counts = max(10, int(round(values["accel_rpm_s"] * ca18 / 60.0)))
    stop_decel_counts = max(100, int(round(
        min(values["accel_rpm_s"], MAX_STOP_DECEL_RPM_S) * ca18 / 60.0)))
    if speed_counts > 2_000_000_000 or accel_counts > 2_000_000_000:
        return MotionResult(RED, "SP/AC exceeds drive numeric range",
                            evidence=evidence)
    abs_ceiling = min(JOG_OVERSPEED_FACTOR * speed_counts, state["VH[2]"])
    overspeed_floor = max(JOG_OVERSPEED_FLOOR_RPM * idle_speed, idle_speed)
    overspeed_margin = idle_speed  # ~1 rpm

    applied = {
        "PL[1]": cap, "CL[1]": cap, "SP": speed_counts,
        "AC": accel_counts, "DC": accel_counts, "SD": stop_decel_counts,
        "FS": 0, "SF[1]": SMOOTHING_MS, "SF[2]": 0,
    }
    evidence.update({
        "original_settings": dict(originals),
        "applied_settings": dict(applied),
        "current_cap_a": cap,
        "abs_ceiling_counts": abs_ceiling,
        "jog_max_rpm": values["speed_rpm"],
        "timebox_s": values["timebox_s"],
        "session_token_present": True,
        # Per-poll enable-transient trace: distinguishes "real current, no torque"
        # (I_vec ~= cap while VX ~= 0 -> commutation delta) from "command capped but
        # current not delivered" (I_vec << cap -> electrical / phase-wire high R).
        "enable_samples": [],
    })

    motion_started = False
    moved = False
    aborted = False
    reason = ""
    try:
        for name in _APPLY_ORDER:
            if cancel_fn():
                raise _MotionAborted("operator cancel while preparing RAM profile")
            _write_verified(link, name, applied[name], token)
        if not (applied["AC"] <= applied["SD"] and applied["DC"] <= applied["SD"]):
            raise _MotionAborted("profile invariant AC/DC <= SD was not satisfied")
        if cancel_fn():
            raise _MotionAborted("operator cancel before enable")
        _assert_same_session(link, token)
        link.command("MO=1", allow_motion=True)
        mo1_at = clock_fn()
        enable_deadline = mo1_at + 1.5
        while True:
            es, _age = _read_active_sample(
                link, ("MO", "SO", "MF", "PS", "SR", "VX", "ID", "IQ"),
                sample_clock_fn=sample_clock_fn)
            if cancel_fn():
                raise _MotionAborted("operator cancel during enable sample")
            sr = int(es["SR"])
            if len(evidence["enable_samples"]) < 128:
                evidence["enable_samples"].append({
                    "t_s": clock_fn() - mo1_at,
                    "SR": sr, "lc": bool(sr & (1 << 13)),
                    "ID": es["ID"], "IQ": es["IQ"],
                    "I_vec_a": _current_vector_a(es["ID"], es["IQ"]),
                    "VX": es["VX"], "cap_a": cap,
                })
            if int(es["MF"]) != 0:
                raise _MotionAborted("drive fault while enabling")
            if int(es["PS"]) == 1:
                raise _MotionAborted("user program started while enabling (PS=1)")
            if sr & _UNSAFE_SR_MASK:
                raise _MotionAborted("unsafe SR status while enabling (SR=%s)" % sr)
            if not (sr & (1 << 14)) or not (sr & (1 << 15)):
                raise _MotionAborted("STO permission dropped while enabling")
            # Real over-current / unintended motion still aborts on sight.  The LC
            # status bit (SR 13) is a limit *selector*, not a saturation signal
            # (see _UNSAFE_SR_MASK) — the current-vector magnitude is what bounds
            # actual current here.
            if (abs(es["VX"]) > idle_speed
                    or _current_vector_a(es["ID"], es["IQ"]) > (
                        cap * (1.0 + CURRENT_LIMIT_REL_MARGIN)
                        + CURRENT_LIMIT_ABS_MARGIN_A)):
                raise _MotionAborted("unintended motion/current while enabling")
            # Enable is complete once the drive reports servo-on (MO=1, SO=1,
            # SR bit 4).  EAS energises and jogs immediately at this point.
            if int(es["MO"]) == 1 and int(es["SO"]) == 1 and bool(sr & (1 << 4)):
                break
            if clock_fn() >= enable_deadline:
                raise _MotionAborted("MO=1 issued but SO=1 was not observed")
            sleep_fn(0.02)

        last_jv = 0
        # Profiler-following expected speed: the overspeed reference tracks the
        # drive profiler ramping toward the commanded JV at AC/DC, so a downshift
        # never false-trips and a stuck-at-old-speed fault is never masked
        # (fable-critic HIGH-2).
        expected_counts = 0.0
        last_tick = clock_fn()
        timebox_deadline = clock_fn() + values["timebox_s"]
        while True:
            now = clock_fn()
            if now >= timebox_deadline:
                reason = ("jog max-duration timebox (%.0f s) reached"
                          % values["timebox_s"])
                break
            if cancel_fn():
                raise _MotionAborted("operator STOP / DRIVE STOP")
            cmd = jog_cmd_fn() or {}
            ts = cmd.get("ts")
            fresh = (isinstance(ts, (int, float))
                     and (now - float(ts)) <= JOG_DEADMAN_AGE_S)
            stop_req = bool(cmd.get("stop")) or not fresh
            raw_rpm = 0.0 if stop_req else float(cmd.get("rpm") or 0.0)
            if not math.isfinite(raw_rpm):   # NaN/inf command -> fail safe to stop
                raw_rpm = 0.0
                stop_req = True
            target_rpm = max(-values["speed_rpm"],
                             min(values["speed_rpm"], raw_rpm))
            target_jv = int(round(target_rpm * ca18 / 60.0))
            if target_jv != last_jv:
                if cancel_fn():
                    raise _MotionAborted("operator STOP / DRIVE STOP")
                _assert_same_session(link, token)
                _write_verified(link, "JV", target_jv, token, allow_motion=True)
                link.command("BG", allow_motion=True)
                motion_started = True
                last_jv = target_jv
            sample, _age = _read_active_sample(
                link, _JOG_SAMPLE_READS, sample_clock_fn=sample_clock_fn)
            if int(sample["MF"]) != 0:
                raise _MotionAborted(
                    "drive fault during jog (MF=0x%X)" % int(sample["MF"]))
            if int(sample["PS"]) == 1:
                raise _MotionAborted("user program started during jog (PS=1)")
            sr = int(sample["SR"])
            if sr & _UNSAFE_SR_MASK:
                raise _MotionAborted("unsafe SR status during jog (SR=%s)" % sr)
            if not (sr & (1 << 14)) or not (sr & (1 << 15)):
                raise _MotionAborted("STO permission dropped during jog")
            if (last_jv != 0
                    and int(sample.get("OV[2]", JOG_PROFILE_VELOCITY_MODE))
                    != JOG_PROFILE_VELOCITY_MODE):
                raise _MotionAborted(
                    "actual motion mode OV[2] is not velocity (3) while jogging")
            current_vector_a = _current_vector_a(sample["ID"], sample["IQ"])
            if current_vector_a > (cap * (1.0 + CURRENT_LIMIT_REL_MARGIN)
                                   + CURRENT_LIMIT_ABS_MARGIN_A):
                raise _MotionAborted(
                    "current vector exceeded bounded jog cap "
                    "(sqrt(ID^2+IQ^2)=%.3f A, cap=%.3f A; native drive amperes)"
                    % (current_vector_a, cap))
            # Profiler-following overspeed reference (fable-critic HIGH-2): advance
            # an expected-speed estimate toward the commanded JV at the applied
            # AC/DC each tick; the limit then follows the real accel/decel
            # envelope, so a mid-decel retarget does not false-trip and a
            # stuck-at-old-speed fault is caught as the expected speed decays
            # below the frozen feedback.  max(expected, target) keeps the
            # accel/first-tick edge from tripping before feedback catches up.
            dt = max(0.0, now - last_tick)
            last_tick = now
            step = float(accel_counts) * dt
            if expected_counts < last_jv:
                expected_counts = min(float(last_jv), expected_counts + step)
            elif expected_counts > last_jv:
                expected_counts = max(float(last_jv), expected_counts - step)
            ref = max(abs(expected_counts), abs(float(last_jv)))
            overspeed_limit = max(
                JOG_OVERSPEED_FACTOR * ref + overspeed_margin, overspeed_floor)
            vx = float(sample["VX"])
            if abs(vx) > overspeed_limit or abs(vx) > abs_ceiling:
                raise _MotionAborted(
                    "overspeed abort: |VX|=%.0f cnt/s > limit %.0f / ceiling %.0f"
                    % (abs(vx), overspeed_limit, abs_ceiling))
            if abs(vx) > JOG_STOP_RPM * idle_speed:
                moved = True
            if emit_fn is not None:
                try:
                    emit_fn(dict(sample))
                except Exception:
                    pass
            if (stop_req and last_jv == 0
                    and abs(vx) <= JOG_STOP_RPM * idle_speed):
                reason = reason or "stopped"
                break
            sleep_fn(JOG_POLL_S)
    except _MotionAborted as exc:
        aborted = True
        reason = str(exc)
    except BaseException as exc:  # noqa: BLE001 - ANY escape must still torque-off
        aborted = True
        reason = "jog exception: %s" % exc

    # Two-tier stop chain: a fault/runaway cannot trust JV=0 deceleration (a bad
    # commutation makes the velocity loop positive feedback), so it goes straight
    # to torque-off; an operator/timebox stop decelerates gently first.
    if aborted:
        stop_result = safe_stop_disable(link, sleep_fn=sleep_fn, clock_fn=clock_fn)
    else:
        try:
            _write_verified(link, "JV", 0, token, allow_motion=True)
            link.command("BG", allow_motion=True)
        except Exception:
            pass
        # Size the settle wait to the real deceleration time (|VX| / SD), not a
        # fixed 2 s that is far shorter than a low-accel decel (fable-critic
        # MEDIUM); keep watching MF so a fault mid-settle still reaches torque-off.
        try:
            s0, _a = _read_active_sample(
                link, ("VX",), sample_clock_fn=sample_clock_fn)
            vx_now = abs(float(s0["VX"]))
        except Exception:
            vx_now = float(speed_counts)
        settle_s = min(
            JOG_STOP_SETTLE_TIMEOUT_S_MAX,
            max(JOG_STOP_SETTLE_TIMEOUT_S,
                vx_now / max(1.0, float(stop_decel_counts)) + 1.0))
        settle_deadline = clock_fn() + settle_s
        while clock_fn() < settle_deadline:
            try:
                s, _a = _read_active_sample(
                    link, ("VX", "MF"), sample_clock_fn=sample_clock_fn)
                if int(s["MF"]) != 0:
                    break   # fault during settle; safe_stop_disable below owns it
                if abs(float(s["VX"])) <= JOG_STOP_RPM * idle_speed:
                    break
            except Exception:
                break
            sleep_fn(0.02)
        stop_result = safe_stop_disable(link, sleep_fn=sleep_fn, clock_fn=clock_fn)

    evidence["stop_result"] = {
        "status": stop_result.status, "reason": stop_result.reason,
        "final_state": dict(stop_result.final_state)}
    evidence["motion_started"] = motion_started
    evidence["moved"] = moved

    # Restore ONLY after torque disable is GREEN-verified (never raise caps while
    # disable is unverified).
    if stop_result.final_state.get("disabled_verified") is True:
        restored_ok, restore_errors = _restore_settings(link, originals, token)
        evidence["settings_restored"] = restored_ok
        evidence["restore_errors"] = restore_errors
        if not restored_ok:
            # Torque is off, but the temporary RAM caps were not fully restored,
            # so the session's real settings are polluted.  Report UNKNOWN (not a
            # GREEN "restored") so the worker latches config-unknown and blocks
            # further motion until it is audited (fable-critic HIGH-1).
            return MotionResult(
                UNKNOWN,
                "jog disabled but temporary RAM settings were NOT fully restored "
                "(%s); config audit required before further motion [%s]"
                % ("; ".join(restore_errors) or "unknown", reason),
                final_state=stop_result.final_state, evidence=evidence)
        if aborted:
            return MotionResult(RED, reason,
                                final_state=stop_result.final_state,
                                evidence=evidence)
        if motion_started and not moved:
            return MotionResult(
                UNKNOWN,
                "jog commanded but no rotation observed; current cap %.2f A may "
                "be below breakaway. Drive disabled and settings restored." % cap,
                final_state=stop_result.final_state, evidence=evidence)
        return MotionResult(
            GREEN, reason or "jog session ended; auto-disabled and restored",
            final_state=stop_result.final_state, evidence=evidence)
    evidence["settings_restored"] = False
    return MotionResult(
        UNKNOWN,
        "jog exit could not verify MO=0/SO=0; kept bounded caps and did not "
        "restore (%s)" % reason, final_state=stop_result.final_state,
        evidence=evidence)
