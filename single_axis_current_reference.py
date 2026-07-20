"""Bounded read-only Current Reference snapshot for one Elmo Gold axis.

The reader issues only the frozen query sequence in :data:`READ_STEPS`.
It never assigns ``TC``, changes ``UM``, enables the motor, changes a current
limit, starts a profiler, or commands motion.  The installed Gold command
reference states that assigning ``TC`` requires the motor to be on and forces
the current control loop in every unit mode, so command authority is a
separate, deliberately unimplemented contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from single_axis_status import format_sr_stability_change


CURRENT = "CURRENT"
UNKNOWN = "UNKNOWN"
CURRENT_DRIVE_READ_ONLY = "CURRENT_DRIVE_READ_ONLY"
AUTHORITY_UNKNOWN = "AUTHORITY_UNKNOWN"
COMMAND_LOCKED_NEED_DATA = "LOCKED_NEED_DATA"

READ_TIMEOUT_MS = 150
MAX_SNAPSHOT_DURATION_S = 1.5
_CURRENT_TOLERANCE_A = 1e-6
_UINT32_MAX = (1 << 32) - 1
_SR_STABILITY_MASK = (
    0xF
    | (1 << 4)
    | (1 << 6)
    | (1 << 13)
    | (1 << 14)
    | (1 << 15)
    | (1 << 22)
    | (1 << 23)
    | (1 << 27)
)

EVIDENCE_LABEL = (
    "CURRENT DRIVE READ · MO/SO/MF/SR PRE+POST · "
    "UM/TC/IQ/ID/CL[1]/PL[1]/LC/MC QUERY ONLY · "
    "NO TC ASSIGNMENT · NO LOOP CHANGE · NO ENABLE/MOTION · "
    "NOT EAS CURRENT TAB: EAS HAS FIVE CURRENT COMMAND PRESETS"
)

READ_STEPS = (
    ("MO_PRE", "MO"),
    ("SO_PRE", "SO"),
    ("MF_PRE", "MF"),
    ("SR_PRE", "SR"),
    ("UM", "UM"),
    ("TC", "TC"),
    ("IQ", "IQ"),
    ("ID", "ID"),
    ("CL[1]", "CL[1]"),
    ("PL[1]", "PL[1]"),
    ("LC", "LC"),
    ("MC", "MC"),
    ("MO_POST", "MO"),
    ("SO_POST", "SO"),
    ("MF_POST", "MF"),
    ("SR_POST", "SR"),
)

_MODE_NAMES = MappingProxyType({
    1: "Torque",
    2: "Speed",
    3: "Stepper",
    5: "Position",
    6: "Stepper open/closed loop",
})


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CurrentCommandContract:
    implemented: bool
    operation_status: str
    requires_motor_on: bool
    requires_servo_ready: bool
    forces_current_loop: bool
    requires_watchdog: bool
    requires_stop_disable_closeout: bool
    boundary: str


@dataclass(frozen=True, slots=True)
class CurrentReferenceSnapshot:
    state: str
    authority: str
    evidence_label: str
    command_authority: str
    motor_state: str
    mode_value: Optional[int]
    mode_name: str
    tc_a: Optional[float]
    iq_a: Optional[float]
    id_a: Optional[float]
    continuous_limit_a: Optional[float]
    peak_limit_a: Optional[float]
    maximum_drive_current_a: Optional[float]
    current_limit_active: Optional[bool]
    limit_relation: str
    raw: Mapping[str, int | float]
    sample_duration_s: Optional[float]
    reason: str


_ROOT = (
    r"C:\Program Files\Elmo Motion Control\Elmo Application Studio III"
    r"\NetHelp\Content\Gold Line Command Reference"
)
SOURCES = (
    DocumentSource(
        "tc", _ROOT + r"\TC Torque Command.htm",
        "E9152A936F2717C747A0382B215D5463966A56B36F7D203D126251C068856CA9",
    ),
    DocumentSource(
        "cl", _ROOT + r"\CL Current Limit Parameters.htm",
        "A881FE3E645E42D417E6E598EE3A8016AA04910277B935DD92AC02999598F48C",
    ),
    DocumentSource(
        "pl", _ROOT + r"\PL N Peak Limit.htm",
        "5A65892FA038EEE704A23F232EC4A901F4A29584345AC02BD7E502A07F5C37D2",
    ),
    DocumentSource(
        "lc", _ROOT + r"\LC Current Limit Flag.htm",
        "08848BA17A1253660849BCAC3DD5966FB8C2628DD46AC0381E2CC66AAE3A1079",
    ),
    DocumentSource(
        "mc", _ROOT + r"\MC Maximum Current.htm",
        "26EBD384B34F4616454A41BECD66DBD193A4093AE5BEC73941D1B7E05C112205",
    ),
    DocumentSource(
        "id_iq", _ROOT + r"\ID IQ Active Reactive Current.htm",
        "2D1E639F7F4C0374E91793CD8085D6ABA85B9E6F3C4F1A04B7C205E5041DB4C2",
    ),
    DocumentSource(
        "um", _ROOT + r"\UM Unit Mode.htm",
        "8E50AC03CD82F119EEAB3A2BC8C311086EF4CB9F03C06F597084EC79BB3277F8",
    ),
    DocumentSource(
        "mo_so", _ROOT + r"\MO SO Motor On Servo On.htm",
        "363632520E982C5B42BAF683ECCDBAA1E59623DC4EEE512B7291DA611C671E37",
    ),
    DocumentSource(
        "sr", _ROOT + r"\SR Status Register.htm",
        "7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF",
    ),
)

COMMAND_CONTRACT = CurrentCommandContract(
    implemented=False,
    operation_status="NEED_DATA",
    requires_motor_on=True,
    requires_servo_ready=True,
    forces_current_loop=True,
    requires_watchdog=True,
    requires_stop_disable_closeout=True,
    boundary=(
        "TC assignment is not implemented. Gold requires MO=1, and the "
        "application must observe SO=1 before any reference. TC is amperes, "
        "is accepted only inside PL[1]/CL[1] behavior, and forces the current "
        "loop even from Position or Speed mode. A future bounded command needs "
        "an independently verified current/thermal/torque envelope, restrained "
        "load, watchdog, abort, exact readback, and ST -> MO=0 closeout."
    ),
)


def _unknown(reason: str) -> CurrentReferenceSnapshot:
    return CurrentReferenceSnapshot(
        state=UNKNOWN,
        authority=AUTHORITY_UNKNOWN,
        evidence_label=EVIDENCE_LABEL,
        command_authority=COMMAND_LOCKED_NEED_DATA,
        motor_state="UNKNOWN",
        mode_value=None,
        mode_name="UNKNOWN",
        tc_a=None,
        iq_a=None,
        id_a=None,
        continuous_limit_a=None,
        peak_limit_a=None,
        maximum_drive_current_a=None,
        current_limit_active=None,
        limit_relation="UNKNOWN",
        raw=MappingProxyType({}),
        sample_duration_s=None,
        reason=str(reason or "current-reference snapshot unavailable"),
    )


def _decimal(raw: Mapping[str, object], key: str) -> Decimal:
    if key not in raw:
        raise ValueError("%s is missing" % key)
    value = raw[key]
    if isinstance(value, bool) or value is None:
        raise ValueError("%s must be a finite number, not %r" % (key, value))
    try:
        number = Decimal(str(value).strip().rstrip(";").strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(
            "%s must be a finite number, not %r" % (key, value)) from exc
    if not number.is_finite():
        raise ValueError("%s must be finite, not %r" % (key, value))
    return number


def _integer(
        raw: Mapping[str, object],
        key: str,
        *,
        minimum: int,
        maximum: int,
) -> int:
    number = _decimal(raw, key)
    if number != number.to_integral_value():
        raise ValueError("%s must be an integer" % key)
    value = int(number)
    if value < minimum or value > maximum:
        raise ValueError(
            "%s=%s is outside %s..%s" %
            (key, value, minimum, maximum))
    return value


def _current(
        raw: Mapping[str, object],
        key: str,
        *,
        minimum: float,
        maximum: float,
        bound_name: str = "",
) -> float:
    value = float(_decimal(raw, key))
    if value < minimum - _CURRENT_TOLERANCE_A:
        raise ValueError(
            "%s=%s is below %s A%s" % (
                key,
                value,
                minimum,
                " (%s bound)" % bound_name if bound_name else "",
            ))
    if value > maximum + _CURRENT_TOLERANCE_A:
        raise ValueError(
            "%s=%s exceeds %s A%s" % (
                key,
                value,
                maximum,
                " (%s bound)" % bound_name if bound_name else "",
            ))
    return value


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


def _validate_sr(
        key: str,
        sr: int,
        *,
        mo: int,
        so: int,
        lc: int,
) -> None:
    if bool(sr & (1 << 22)) != bool(mo):
        raise ValueError("%s Motor On bit disagrees with MO" % key)
    if bool(sr & (1 << 4)) != bool(so):
        raise ValueError("%s Servo Enabled bit disagrees with SO" % key)
    if bool(sr & (1 << 13)) != bool(lc):
        raise ValueError(
            "%s current-limit bit disagrees with LC" % key)


def _motor_state(mo: int, so: int, mf: int, sr: int) -> str:
    if mf != 0 or (sr & 0xF) != 0 or bool(sr & (1 << 6)):
        return "FAULT REPORTED · COMMAND LOCKED"
    if mo == 0 and so == 0:
        return "DISABLED REPORTED"
    if mo == 1 and so == 0:
        return "ENABLE REQUESTED · REFERENCES BLOCKED"
    if mo == 1 and so == 1:
        return "ENABLED REPORTED · ENERGIZED"
    return "DISABLING / BRAKE HOLD REPORTED"


def decode_current_reference_snapshot(
        raw: Mapping[str, object] | None,
        *,
        sample_duration_s: object,
) -> CurrentReferenceSnapshot:
    """Decode one bounded query set without performing drive I/O."""
    if not isinstance(raw, Mapping):
        return _unknown("raw current-reference mapping is missing")
    try:
        duration = _duration(sample_duration_s)
        mo_pre = _integer(raw, "MO_PRE", minimum=0, maximum=1)
        so_pre = _integer(raw, "SO_PRE", minimum=0, maximum=1)
        mf_pre = _integer(
            raw, "MF_PRE", minimum=0, maximum=_UINT32_MAX)
        sr_pre = _integer(
            raw, "SR_PRE", minimum=0, maximum=_UINT32_MAX)
        mo_post = _integer(raw, "MO_POST", minimum=0, maximum=1)
        so_post = _integer(raw, "SO_POST", minimum=0, maximum=1)
        mf_post = _integer(
            raw, "MF_POST", minimum=0, maximum=_UINT32_MAX)
        sr_post = _integer(
            raw, "SR_POST", minimum=0, maximum=_UINT32_MAX)
        lc = _integer(raw, "LC", minimum=0, maximum=1)

        if (mo_pre, so_pre, mf_pre) != (mo_post, so_post, mf_post):
            raise ValueError(
                "MO/SO/MF changed during current-reference acquisition")
        _validate_sr("SR_PRE", sr_pre, mo=mo_pre, so=so_pre, lc=lc)
        _validate_sr("SR_POST", sr_post, mo=mo_post, so=so_post, lc=lc)
        if (sr_pre & _SR_STABILITY_MASK) != (
                sr_post & _SR_STABILITY_MASK):
            raise ValueError(
                "SR safety/current state changed during acquisition: %s"
                % format_sr_stability_change(
                    sr_pre,
                    sr_post,
                    mask=_SR_STABILITY_MASK,
                ))

        mode = _integer(raw, "UM", minimum=1, maximum=6)
        if mode not in _MODE_NAMES:
            raise ValueError("UM=%s is reserved or unsupported" % mode)
        mc = _current(raw, "MC", minimum=0.0, maximum=1e6)
        continuous = _current(
            raw, "CL[1]", minimum=0.0, maximum=mc, bound_name="MC")
        peak = _current(
            raw, "PL[1]", minimum=0.0, maximum=mc, bound_name="MC")
        tc = _current(
            raw, "TC", minimum=-peak, maximum=peak, bound_name="PL[1]")
        iq = _current(
            raw, "IQ", minimum=-mc, maximum=mc, bound_name="MC")
        id_value = _current(
            raw, "ID", minimum=-mc, maximum=mc, bound_name="MC")
        if mo_post == 0 and (
                abs(iq) > _CURRENT_TOLERANCE_A
                or abs(id_value) > _CURRENT_TOLERANCE_A):
            raise ValueError(
                "IQ/ID must report 0 when MO=0 according to installed Gold docs")

        normalized: dict[str, int | float] = {
            "MO_PRE": mo_pre,
            "SO_PRE": so_pre,
            "MF_PRE": mf_pre,
            "SR_PRE": sr_pre,
            "UM": mode,
            "TC": tc,
            "IQ": iq,
            "ID": id_value,
            "CL[1]": continuous,
            "PL[1]": peak,
            "LC": lc,
            "MC": mc,
            "MO_POST": mo_post,
            "SO_POST": so_post,
            "MF_POST": mf_post,
            "SR_POST": sr_post,
        }
    except (TypeError, ValueError, OverflowError) as exc:
        return _unknown(str(exc))

    relation = (
        "CL[1] <= PL[1] <= MC"
        if continuous <= peak + _CURRENT_TOLERANCE_A
        else "CL[1] > PL[1] · CL[1] documented as ineffective"
    )
    return CurrentReferenceSnapshot(
        state=CURRENT,
        authority=CURRENT_DRIVE_READ_ONLY,
        evidence_label=EVIDENCE_LABEL,
        command_authority=COMMAND_LOCKED_NEED_DATA,
        motor_state=_motor_state(mo_post, so_post, mf_post, sr_post),
        mode_value=mode,
        mode_name=_MODE_NAMES[mode],
        tc_a=tc,
        iq_a=iq,
        id_a=id_value,
        continuous_limit_a=continuous,
        peak_limit_a=peak,
        maximum_drive_current_a=mc,
        current_limit_active=bool(lc),
        limit_relation=relation,
        raw=MappingProxyType(normalized),
        sample_duration_s=duration,
        reason="",
    )


def read_current_reference_snapshot(
        link: Any,
        *,
        clock_fn: Callable[[], float] = time.monotonic,
) -> CurrentReferenceSnapshot:
    """Read the exact bounded query sequence in one identity-bound session."""
    get_session = getattr(link, "transaction_session_identity", None)
    if not callable(get_session):
        return _unknown("drive session identity API is unavailable")
    session = get_session()
    if session is None:
        return _unknown("drive session identity is unavailable")
    raw: dict[str, object] = {}
    try:
        started = float(clock_fn())
        if not math.isfinite(started):
            raise ValueError("sample start clock is not finite")
        for key, command in READ_STEPS:
            try:
                raw[key] = link.command(
                    command, timeout_ms=READ_TIMEOUT_MS)
            except Exception as exc:
                raise RuntimeError(
                    "%s read failed: %s" % (command, exc)) from exc
        finished = float(clock_fn())
        if not math.isfinite(finished):
            raise ValueError("sample finish clock is not finite")
        if get_session() is not session:
            raise RuntimeError(
                "drive session changed during current-reference read")
        return decode_current_reference_snapshot(
            raw, sample_duration_s=finished - started)
    except Exception as exc:
        return _unknown(str(exc))
