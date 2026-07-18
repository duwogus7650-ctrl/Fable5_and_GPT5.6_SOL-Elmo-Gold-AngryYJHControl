"""Pure read-only projection of an Elmo Single Axis status snapshot.

The decoder consumes values already returned by ``read_axis_summary``.  It
performs no drive I/O and grants no motion, enable, tuning, persistence, or
hardware-safety authority.  SR meanings are a MODEL projection from the local
2013 Gold command reference and are not proof that either STO channel or an
independent emergency-stop path was tested.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from types import MappingProxyType
from typing import Mapping, Optional


CURRENT = "CURRENT"
UNKNOWN = "UNKNOWN"
INCONSISTENT = "INCONSISTENT"

MODEL_CURRENT = "MODEL CURRENT"
MODEL_UNKNOWN = "MODEL AUTHORITY UNKNOWN"

EVIDENCE_LABEL = (
    "DRIVE-REPORTED · MODEL DECODE · NOT STO TEST EVIDENCE")

_REQUIRED = ("MO", "SO", "MF", "PS", "SR", "MS")
_UINT32_MAX = (1 << 32) - 1
_SR_DEFINED_MASK = (
    0xF
    | (1 << 4)
    | (1 << 6)
    | (1 << 7)
    | (0xF << 8)
    | (1 << 12)
    | (1 << 13)
    | (1 << 14)
    | (1 << 15)
    | (0x3 << 16)
    | (1 << 18)
    | (0x7 << 24)
    | (1 << 28)
)

_AMPLIFIER_LABELS = MappingProxyType({
    0x0: "0x0 · no instantaneous amplifier code reported",
    0x3: "0x3 · undervoltage reported",
    0x5: "0x5 · overvoltage reported",
    0x7: "0x7 · safety-input state reported",
    0xB: "0xB · short protection reported",
    0xD: "0xD · overtemperature reported",
})


@dataclass(frozen=True)
class AxisSafetySnapshot:
    """One immutable, non-authoritative projection of raw axis status."""

    state: str
    authority: str
    evidence_label: str
    raw: Mapping[str, int]
    amplifier_code: Optional[int]
    amplifier_label: str
    servo_enabled_reported: Optional[bool]
    enabled_fault_reported: Optional[bool]
    homing_capture_reported: Optional[bool]
    profiler_code: Optional[int]
    user_program_reported: Optional[bool]
    current_limit_reported: Optional[bool]
    sto1_permission_reported: Optional[bool]
    sto2_permission_reported: Optional[bool]
    recorder_code: Optional[int]
    target_reached_reported: Optional[bool]
    hall_state: Optional[int]
    stopped_by_switch_reported: Optional[bool]
    conflicts: tuple[str, ...]
    conditions: tuple[str, ...]
    reason: str


def _unknown(reason: str) -> AxisSafetySnapshot:
    return AxisSafetySnapshot(
        state=UNKNOWN,
        authority=MODEL_UNKNOWN,
        evidence_label=EVIDENCE_LABEL,
        raw=MappingProxyType({}),
        amplifier_code=None,
        amplifier_label="—",
        servo_enabled_reported=None,
        enabled_fault_reported=None,
        homing_capture_reported=None,
        profiler_code=None,
        user_program_reported=None,
        current_limit_reported=None,
        sto1_permission_reported=None,
        sto2_permission_reported=None,
        recorder_code=None,
        target_reached_reported=None,
        hall_state=None,
        stopped_by_switch_reported=None,
        conflicts=(),
        conditions=(),
        reason=str(reason or "snapshot unavailable"),
    )


def _integer(
        raw: Mapping[str, object],
        key: str,
        *,
        allowed: Optional[frozenset[int]] = None,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
) -> int:
    if key not in raw:
        raise ValueError("%s is missing" % key)
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("%s must be a finite integer, not %r" % (key, value))
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "%s must be a finite integer, not %r" % (key, value)) from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError("%s must be a finite integer, not %r" % (key, value))
    result = int(value)
    if allowed is not None and result not in allowed:
        raise ValueError(
            "%s=%s is outside the documented projection set" % (key, result))
    if minimum is not None and result < minimum:
        raise ValueError("%s=%s is below %s" % (key, result, minimum))
    if maximum is not None and result > maximum:
        raise ValueError("%s=%s exceeds %s" % (key, result, maximum))
    return result


def decode_axis_safety_snapshot(
        raw: Mapping[str, object] | None) -> AxisSafetySnapshot:
    """Decode existing MO/SO/MF/PS/SR/MS values without issuing drive I/O.

    Invalid or incomplete input blanks the entire semantic projection.  When
    redundant SO/SR4 or PS/SR12 observations disagree, raw values remain
    visible but model authority is revoked as ``INCONSISTENT``.
    """
    if not isinstance(raw, Mapping):
        return _unknown("raw snapshot mapping is missing")

    try:
        values = {
            "MO": _integer(raw, "MO", allowed=frozenset((0, 1))),
            "SO": _integer(raw, "SO", allowed=frozenset((0, 1))),
            "MF": _integer(raw, "MF", minimum=0, maximum=0x7FFFFFFF),
            "PS": _integer(
                raw, "PS", allowed=frozenset((-2, -1, 0, 1))),
            "SR": _integer(raw, "SR", minimum=0, maximum=_UINT32_MAX),
            "MS": _integer(raw, "MS", allowed=frozenset((0, 1, 2, 3))),
        }
    except ValueError as exc:
        return _unknown(str(exc))

    sr = values["SR"]
    reserved_bits = sr & (~_SR_DEFINED_MASK & _UINT32_MAX)
    if reserved_bits:
        return _unknown(
            "SR has reserved bits set: 0x%08X" % reserved_bits)
    amplifier_code = sr & 0xF
    if amplifier_code not in _AMPLIFIER_LABELS:
        return _unknown(
            "SR amplifier code 0x%X is reserved or unmapped" % amplifier_code)
    amplifier_label = _AMPLIFIER_LABELS[amplifier_code]
    servo_enabled = bool(sr & (1 << 4))
    enabled_fault = bool(sr & (1 << 6))
    homing_capture = bool(sr & (1 << 7))
    profiler_code = (sr >> 8) & 0xF
    if profiler_code > 10:
        return _unknown(
            "SR profiler code %d is reserved or unmapped" % profiler_code)
    user_program = bool(sr & (1 << 12))
    current_limit = bool(sr & (1 << 13))
    sto1_permission = bool(sr & (1 << 14))
    sto2_permission = bool(sr & (1 << 15))
    recorder_code = (sr >> 16) & 0x3
    target_reached = bool(sr & (1 << 18))
    hall_state = (sr >> 24) & 0x7
    stopped_by_switch = bool(sr & (1 << 28))

    conflicts: list[str] = []
    if bool(values["SO"]) != servo_enabled:
        conflicts.append(
            "SO=%d disagrees with SR4=%d" %
            (values["SO"], int(servo_enabled)))
    if (values["PS"] == 1) != user_program:
        conflicts.append(
            "PS=%d disagrees with SR12=%d" %
            (values["PS"], int(user_program)))

    conditions: list[str] = [
        "SR4 servo-enabled report=%d" % int(servo_enabled),
        "STO1 drive-reported permission=%d" % int(sto1_permission),
        "STO2 drive-reported permission=%d" % int(sto2_permission),
    ]
    if values["MF"] != 0:
        conditions.append("MF raw fault=%d" % values["MF"])
    if amplifier_code != 0:
        conditions.append(
            "Amplifier instantaneous code=0x%X" % amplifier_code)
    if enabled_fault:
        conditions.append("SR6 enable-time fault report=1")
    if homing_capture:
        conditions.append("SR7 homing/capture report=1")
    if user_program:
        conditions.append("SR12 user-program report=1")
    if current_limit:
        conditions.append("SR13 current-limit report=1")
    if stopped_by_switch:
        conditions.append("SR28 profiler-stop-by-switch report=1")

    state = INCONSISTENT if conflicts else CURRENT
    authority = MODEL_UNKNOWN if conflicts else MODEL_CURRENT
    return AxisSafetySnapshot(
        state=state,
        authority=authority,
        evidence_label=EVIDENCE_LABEL,
        raw=MappingProxyType(values),
        amplifier_code=amplifier_code,
        amplifier_label=amplifier_label,
        servo_enabled_reported=servo_enabled,
        enabled_fault_reported=enabled_fault,
        homing_capture_reported=homing_capture,
        profiler_code=profiler_code,
        user_program_reported=user_program,
        current_limit_reported=current_limit,
        sto1_permission_reported=sto1_permission,
        sto2_permission_reported=sto2_permission,
        recorder_code=recorder_code,
        target_reached_reported=target_reached,
        hall_state=hall_state,
        stopped_by_switch_reported=stopped_by_switch,
        conflicts=tuple(conflicts),
        conditions=tuple(conditions),
        reason="; ".join(conflicts),
    )
