"""Bounded read-only Unit Mode (UM) snapshot for one Gold axis.

The reader issues exactly one ``UM`` query in the current identity-bound
transport session.  It never assigns ``UM``, changes a control loop, enables
the drive, commands a reference, or performs motion.  The installed Gold
command reference describes UM as read/write and non-volatile and requires
the motor to be off for a UM assignment, so change authority is deliberately
kept separate and unimplemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional


CURRENT = "CURRENT"
UNKNOWN = "UNKNOWN"
CURRENT_DRIVE_READ_ONLY = "CURRENT_DRIVE_READ_ONLY"
AUTHORITY_UNKNOWN = "AUTHORITY_UNKNOWN"

READ_TIMEOUT_MS = 150
MAX_SNAPSHOT_DURATION_S = 0.5

EVIDENCE_LABEL = (
    "CURRENT DRIVE READ · UM QUERY ONLY · DOCUMENTED GOLD MODE MAP · "
    "NO UM ASSIGNMENT · NO MODE CHANGE · NO ENABLE/REFERENCE/MOTION"
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ModeSpec:
    value: int
    name: str
    highest_control_loop: str
    reference_contract: str
    consequence: str


@dataclass(frozen=True, slots=True)
class ModeChangeContract:
    implemented: bool
    operation_status: str
    nonvolatile: bool
    motor_must_be_off: bool
    requires_exact_readback: bool
    requires_rollback_authority: bool
    boundary: str


@dataclass(frozen=True, slots=True)
class DriveModeSnapshot:
    state: str
    authority: str
    evidence_label: str
    mode: Optional[ModeSpec]
    raw: Mapping[str, int]
    sample_duration_s: Optional[float]
    reason: str


MODE_SPECS = MappingProxyType({
    1: ModeSpec(
        1,
        "Torque",
        "Torque control loop",
        "TC · processed in the next control loop",
        "Direct torque/current reference path",
    ),
    2: ModeSpec(
        2,
        "Speed",
        "Speed control loop",
        "JV · applied after BG; TC forces torque loop",
        "Velocity reference path; cyclic synchronous velocity is documented",
    ),
    3: ModeSpec(
        3,
        "Stepper",
        "Current loop only",
        "PA / PR / JV / TC · open-loop electrical degrees",
        "512 ticks per pole pair; TC excites the motor phases",
    ),
    5: ModeSpec(
        5,
        "Position",
        "Position loop, single or dual",
        "PA / PR · JV may force velocity; TC may force torque",
        "Position reference path; cyclic synchronous position is documented",
    ),
    6: ModeSpec(
        6,
        "Stepper open/closed loop",
        "Current or position control according to stepper configuration",
        "HT[] / FF[] · sensor ID=34 required for closed loop",
        "512 ticks per pole pair; open- and closed-loop variants",
    ),
})

RESERVED_MODES = MappingProxyType({4: "Reserved"})

CHANGE_CONTRACT = ModeChangeContract(
    implemented=False,
    operation_status="NEED_DATA",
    nonvolatile=True,
    motor_must_be_off=True,
    requires_exact_readback=True,
    requires_rollback_authority=True,
    boundary=(
        "UM change is not implemented. The installed Gold command reference "
        "marks UM non-volatile and requires the motor to be off. Any future "
        "assignment also requires verified identity, fresh disabled/stationary "
        "state, exact readback, persistence recovery, and rollback authority."
    ),
)

SOURCES = (
    DocumentSource(
        "gold_um",
        r"C:\Program Files\Elmo Motion Control\Elmo Application Studio III"
        r"\NetHelp\Content\Gold Line Command Reference\UM Unit Mode.htm",
        "8E50AC03CD82F119EEAB3A2BC8C311086EF4CB9F03C06F597084EC79BB3277F8",
    ),
)


def _unknown(reason: str) -> DriveModeSnapshot:
    return DriveModeSnapshot(
        state=UNKNOWN,
        authority=AUTHORITY_UNKNOWN,
        evidence_label=EVIDENCE_LABEL,
        mode=None,
        raw=MappingProxyType({}),
        sample_duration_s=None,
        reason=str(reason or "drive-mode snapshot unavailable"),
    )


def _duration(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("sample duration must be a finite number")
    try:
        duration = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("sample duration must be a finite number") from exc
    if (not math.isfinite(duration)
            or duration < 0.0
            or duration > MAX_SNAPSHOT_DURATION_S):
        raise ValueError(
            "sample duration must be 0..%.3f s" %
            MAX_SNAPSHOT_DURATION_S)
    return duration


def _mode_value(raw: Mapping[str, object]) -> int:
    if "UM" not in raw:
        raise ValueError("UM is missing")
    value = raw["UM"]
    if isinstance(value, bool) or value is None:
        raise ValueError("UM must be a finite documented integer")
    try:
        number = Decimal(str(value).strip().rstrip(";").strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("UM must be a finite documented integer") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError("UM must be a finite documented integer")
    result = int(number)
    if result in RESERVED_MODES:
        raise ValueError("UM=%d is reserved" % result)
    if result not in MODE_SPECS:
        raise ValueError(
            "UM=%d is outside the documented supported set 1,2,3,5,6" %
            result)
    return result


def decode_drive_mode_snapshot(
        raw: Mapping[str, object] | None,
        *,
        sample_duration_s: object,
) -> DriveModeSnapshot:
    """Decode one exact UM observation without performing drive I/O."""
    if not isinstance(raw, Mapping):
        return _unknown("raw drive-mode mapping is missing")
    try:
        duration = _duration(sample_duration_s)
        value = _mode_value(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        return _unknown(str(exc))
    return DriveModeSnapshot(
        state=CURRENT,
        authority=CURRENT_DRIVE_READ_ONLY,
        evidence_label=EVIDENCE_LABEL,
        mode=MODE_SPECS[value],
        raw=MappingProxyType({"UM": value}),
        sample_duration_s=duration,
        reason="",
    )


def read_drive_mode_snapshot(
        link: Any,
        *,
        clock_fn: Callable[[], float] = time.monotonic,
) -> DriveModeSnapshot:
    """Read exactly one UM value and bind it to one transport session."""
    get_session = getattr(link, "transaction_session_identity", None)
    if not callable(get_session):
        return _unknown("drive session identity API is unavailable")
    session = get_session()
    if session is None:
        return _unknown("drive session identity is unavailable")
    try:
        started = float(clock_fn())
        if not math.isfinite(started):
            raise ValueError("sample start clock is not finite")
        try:
            raw_um = link.command("UM", timeout_ms=READ_TIMEOUT_MS)
        except Exception as exc:
            raise RuntimeError("UM read failed: %s" % exc) from exc
        finished = float(clock_fn())
        if not math.isfinite(finished):
            raise ValueError("sample finish clock is not finite")
        if get_session() is not session:
            raise RuntimeError("drive session changed during UM read")
        return decode_drive_mode_snapshot(
            {"UM": raw_um},
            sample_duration_s=finished - started,
        )
    except Exception as exc:
        return _unknown(str(exc))
