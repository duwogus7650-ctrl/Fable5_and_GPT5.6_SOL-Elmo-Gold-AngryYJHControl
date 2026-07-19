"""Bounded read-only position/velocity reference snapshot for one Gold axis.

The values returned by this module are configured or queued drive parameters
and live feedback.  They are not proof that a command is active.  The reader
never assigns PA/PR/JV, calls BG, changes UM, enables the motor, or commands
motion.
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
_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1
_UINT32_MAX = (1 << 32) - 1
_VX_ABS_MAX_COUNT_PER_S = 2_000_000_000.0
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
    "CURRENT DRIVE READ / MO/SO/MF/SR PRE+POST / "
    "UM/PA[1]/PR[1]/JV/SP[1]/AC[1]/DC/SD/PX/PU/XM/FC/CA[45]/VX "
    "QUERY ONLY / "
    "NO ASSIGNMENT / NO BG / NO ENABLE OR MOTION"
)
REFERENCE_SEMANTICS = (
    "CONFIGURED / QUEUED READBACK - NOT ACTIVE COMMAND OR MOTION PROOF · "
    "2026-07-19 LIVE EAS SINGLE AXIS USES PU (DS402 0x6064), NOT RAW PX · "
    "OBSERVED PU-PX=2^25 WITH FC=1, XM=0, CA[45]=1 · "
    "COORDINATE DIVERGENCE / NEED-DATA"
)

READ_STEPS = (
    ("MO_PRE", "MO"),
    ("SO_PRE", "SO"),
    ("MF_PRE", "MF"),
    ("SR_PRE", "SR"),
    ("UM", "UM"),
    ("PA[1]", "PA[1]"),
    ("PR[1]", "PR[1]"),
    ("JV", "JV"),
    ("SP[1]", "SP[1]"),
    ("AC[1]", "AC[1]"),
    ("DC", "DC"),
    ("SD", "SD"),
    ("PX", "PX"),
    ("PU", "PU"),
    ("XM[1]", "XM[1]"),
    ("XM[2]", "XM[2]"),
    ("FC[1]", "FC[1]"),
    ("FC[2]", "FC[2]"),
    ("FC[5]", "FC[5]"),
    ("FC[6]", "FC[6]"),
    ("FC[7]", "FC[7]"),
    ("FC[8]", "FC[8]"),
    ("CA[45]", "CA[45]"),
    ("VX", "VX"),
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
class PositionVelocityCommandContract:
    implemented: bool
    operation_status: str
    requires_motor_on: bool
    requires_servo_ready: bool
    requires_begin_motion: bool
    requires_position_and_velocity_limits: bool
    requires_watchdog: bool
    requires_stop_disable_closeout: bool
    boundary: str


@dataclass(frozen=True, slots=True)
class PositionVelocitySnapshot:
    state: str
    authority: str
    evidence_label: str
    command_authority: str
    reference_semantics: str
    motor_state: str
    mode_value: Optional[int]
    mode_name: str
    absolute_target_count: Optional[int]
    relative_target_count: Optional[int]
    jog_velocity_count_per_s: Optional[int]
    profile_speed_count_per_s: Optional[int]
    acceleration_count_per_s2: Optional[int]
    deceleration_count_per_s2: Optional[int]
    stop_deceleration_count_per_s2: Optional[int]
    effective_acceleration_count_per_s2: Optional[int]
    effective_deceleration_count_per_s2: Optional[int]
    feedback_position_count: Optional[int]
    eas_position_user_unit: Optional[int]
    eas_to_raw_position_delta: Optional[int]
    position_coordinate_status: str
    main_position_socket: Optional[int]
    position_modulo_min: Optional[int]
    position_modulo_max: Optional[int]
    position_scale_numerator: Optional[int]
    position_scale_denominator: Optional[int]
    feedback_velocity_count_per_s: Optional[float]
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
        "pa", _ROOT + r"\PA N Position Absolute.htm",
        "40F8B55DDCED8C0BE6A3ACB88BD0E15A8E35C4CD12C22C5BF0047E4BBE4978F9",
    ),
    DocumentSource(
        "pr", _ROOT + r"\PR N Position Relative.htm",
        "245BBA0F05357FAE5D3AE98A67734D5C36D8BB0B7371F0F620F1C70DCBDD3B4D",
    ),
    DocumentSource(
        "jv", _ROOT + r"\JV Jog Velocity.htm",
        "9C0C536586335AF2FFB1CDEA2EFC63937476C2401E5655F81A8DD48AF92BDBEA",
    ),
    DocumentSource(
        "sp", _ROOT + r"\SP N PTP Profiler Speed.htm",
        "3CB54282817987E3B752A810D04B7B52CE4CF191D5650AF8E70FBF04F39CD8D5",
    ),
    DocumentSource(
        "ac", _ROOT + r"\AC N Set Acceleration.htm",
        "B9AA59CFD00F017A6CFE6D10D5DB1BC1D7093BD47CDB1D5E3F397CA7481120F7",
    ),
    DocumentSource(
        "dc", _ROOT + r"\DC Set Deceleration.htm",
        "75C1C5452D495BA796D99FD868F46A3029A9A2E008EE93F07A18550ECAF39554",
    ),
    DocumentSource(
        "sd", _ROOT + r"\SD Stop Deceleration.htm",
        "785E2AEDF1CB90A71DF41349742DD2ED207BCAD6FDCF1226D38C3EC38D24E935",
    ),
    DocumentSource(
        "px", _ROOT + r"\PX Main Position in Counts.htm",
        "AF2BE7117C4816FB815D16C7F05CE5B44098D5A8B28B7BE2A1666EAD5F93E363",
    ),
    DocumentSource(
        "pu", _ROOT + r"\PU Main Position in User Defined.htm",
        "E1BD14DB1510B0DE916037687C402263E74C8BC7E235B112636DE55553DCA4A0",
    ),
    DocumentSource(
        "xm", _ROOT + r"\XM Position Modulo.htm",
        "50438049A6EB55D7D1461AE25EA77E747FF4CE8D565735027E912357132C49BC",
    ),
    DocumentSource(
        "fc", _ROOT + r"\FC Scaling Factors.htm",
        "2FE1386BF29F30C9596F7E59667925319FEC3D359305C27456AD26C853A45E62",
    ),
    DocumentSource(
        "ca", _ROOT + r"\CA N Commutation Array.htm",
        "2257B5B588F4EE15BEF937328FCC07B9EAD29654B1A9F6FB19D20FC497122BCD",
    ),
    DocumentSource(
        "vx", _ROOT + r"\VX Main Feedback Velocity.htm",
        "A6D910DFCB93AD746B57EE8D12A6EC807BCB573FE05ACF4F1A2D3FDE0D74CD7A",
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
        "mf", _ROOT + r"\MF Drive Fault.htm",
        "2145352F50DA457DF5EEDA45F4D8B505C4E9EF5D7B911F7DE7C437F864A36307",
    ),
    DocumentSource(
        "sr", _ROOT + r"\SR Status Register.htm",
        "7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF",
    ),
)

COMMAND_CONTRACT = PositionVelocityCommandContract(
    implemented=False,
    operation_status="NEED_DATA",
    requires_motor_on=True,
    requires_servo_ready=True,
    requires_begin_motion=True,
    requires_position_and_velocity_limits=True,
    requires_watchdog=True,
    requires_stop_disable_closeout=True,
    boundary=(
        "PA/PR/JV assignment and BG execution are not implemented. A future "
        "bounded command requires MO=1, observed SO=1, verified units and "
        "direction, position/velocity/acceleration limits, restrained load, "
        "watchdog, independent abort, exact readback, and ST -> MO=0 closeout."
    ),
)


def _unknown(reason: str) -> PositionVelocitySnapshot:
    return PositionVelocitySnapshot(
        state=UNKNOWN,
        authority=AUTHORITY_UNKNOWN,
        evidence_label=EVIDENCE_LABEL,
        command_authority=COMMAND_LOCKED_NEED_DATA,
        reference_semantics=REFERENCE_SEMANTICS,
        motor_state="UNKNOWN",
        mode_value=None,
        mode_name="UNKNOWN",
        absolute_target_count=None,
        relative_target_count=None,
        jog_velocity_count_per_s=None,
        profile_speed_count_per_s=None,
        acceleration_count_per_s2=None,
        deceleration_count_per_s2=None,
        stop_deceleration_count_per_s2=None,
        effective_acceleration_count_per_s2=None,
        effective_deceleration_count_per_s2=None,
        feedback_position_count=None,
        eas_position_user_unit=None,
        eas_to_raw_position_delta=None,
        position_coordinate_status="UNKNOWN",
        main_position_socket=None,
        position_modulo_min=None,
        position_modulo_max=None,
        position_scale_numerator=None,
        position_scale_denominator=None,
        feedback_velocity_count_per_s=None,
        limit_relation="UNKNOWN",
        raw=MappingProxyType({}),
        sample_duration_s=None,
        reason=str(reason or "position/velocity snapshot unavailable"),
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


def _finite_float(
        raw: Mapping[str, object],
        key: str,
        *,
        minimum: float,
        maximum: float,
) -> float:
    value = float(_decimal(raw, key))
    if value < minimum or value > maximum:
        raise ValueError(
            "%s=%s is outside %s..%s" %
            (key, value, minimum, maximum))
    return value


def _duration(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("sample duration must be a finite number")
    try:
        duration = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("sample duration must be a finite number") from exc
    if (
            not math.isfinite(duration)
            or duration < 0.0
            or duration > MAX_SNAPSHOT_DURATION_S):
        raise ValueError(
            "sample duration must be 0..%.3f s" %
            MAX_SNAPSHOT_DURATION_S)
    return duration


def _validate_sr(key: str, sr: int, *, mo: int, so: int) -> None:
    if bool(sr & (1 << 22)) != bool(mo):
        raise ValueError("%s Motor On bit disagrees with MO" % key)
    if bool(sr & (1 << 4)) != bool(so):
        raise ValueError("%s Servo Enabled bit disagrees with SO" % key)


def _motor_state(mo: int, so: int, mf: int, sr: int) -> str:
    if mf != 0 or (sr & 0xF) != 0 or bool(sr & (1 << 6)):
        return "FAULT REPORTED / COMMAND LOCKED"
    if mo == 0 and so == 0:
        return "DISABLED REPORTED"
    if mo == 1 and so == 0:
        return "ENABLE REQUESTED / REFERENCES BLOCKED"
    if mo == 1 and so == 1:
        return "ENABLED REPORTED / ENERGIZED"
    return "DISABLING / BRAKE HOLD REPORTED"


def decode_position_velocity_snapshot(
        raw: Mapping[str, object] | None,
        *,
        sample_duration_s: object,
) -> PositionVelocitySnapshot:
    """Decode one bounded query set without performing drive I/O."""
    if not isinstance(raw, Mapping):
        return _unknown("raw position/velocity mapping is missing")
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

        if (mo_pre, so_pre, mf_pre) != (mo_post, so_post, mf_post):
            raise ValueError(
                "MO/SO/MF changed during position/velocity acquisition")
        _validate_sr("SR_PRE", sr_pre, mo=mo_pre, so=so_pre)
        _validate_sr("SR_POST", sr_post, mo=mo_post, so=so_post)
        if (sr_pre & _SR_STABILITY_MASK) != (
                sr_post & _SR_STABILITY_MASK):
            raise ValueError(
                "SR safety/motion state changed during acquisition: %s"
                % format_sr_stability_change(
                    sr_pre,
                    sr_post,
                    mask=_SR_STABILITY_MASK,
                ))

        mode = _integer(raw, "UM", minimum=1, maximum=6)
        if mode not in _MODE_NAMES:
            raise ValueError("UM=%s is reserved or unsupported" % mode)
        pa = _integer(
            raw, "PA[1]", minimum=_INT32_MIN, maximum=_INT32_MAX)
        pr = _integer(
            raw, "PR[1]", minimum=_INT32_MIN, maximum=_INT32_MAX)
        jv = _integer(
            raw, "JV", minimum=_INT32_MIN, maximum=_INT32_MAX)
        sp = _integer(
            raw, "SP[1]", minimum=0, maximum=_INT32_MAX)
        ac = _integer(
            raw, "AC[1]", minimum=1, maximum=_INT32_MAX)
        dc = _integer(raw, "DC", minimum=1, maximum=_INT32_MAX)
        sd = _integer(raw, "SD", minimum=1, maximum=_INT32_MAX)
        px = _integer(
            raw, "PX", minimum=_INT32_MIN, maximum=_INT32_MAX)
        pu = _integer(
            raw, "PU", minimum=_INT32_MIN, maximum=_INT32_MAX)
        xm_min = _integer(
            raw, "XM[1]", minimum=_INT32_MIN, maximum=_INT32_MAX)
        xm_max = _integer(
            raw, "XM[2]", minimum=_INT32_MIN, maximum=_INT32_MAX)
        fc_1 = _integer(raw, "FC[1]", minimum=1, maximum=_INT32_MAX)
        fc_2 = _integer(raw, "FC[2]", minimum=1, maximum=_INT32_MAX)
        fc_5 = _integer(raw, "FC[5]", minimum=1, maximum=_INT32_MAX)
        fc_6 = _integer(raw, "FC[6]", minimum=1, maximum=_INT32_MAX)
        fc_7 = _integer(raw, "FC[7]", minimum=1, maximum=_INT32_MAX)
        fc_8 = _integer(raw, "FC[8]", minimum=1, maximum=_INT32_MAX)
        main_socket = _integer(
            raw, "CA[45]", minimum=1, maximum=4)
        vx = _finite_float(
            raw,
            "VX",
            minimum=-_VX_ABS_MAX_COUNT_PER_S,
            maximum=_VX_ABS_MAX_COUNT_PER_S,
        )

        normalized: dict[str, int | float] = {
            "MO_PRE": mo_pre,
            "SO_PRE": so_pre,
            "MF_PRE": mf_pre,
            "SR_PRE": sr_pre,
            "UM": mode,
            "PA[1]": pa,
            "PR[1]": pr,
            "JV": jv,
            "SP[1]": sp,
            "AC[1]": ac,
            "DC": dc,
            "SD": sd,
            "PX": px,
            "PU": pu,
            "XM[1]": xm_min,
            "XM[2]": xm_max,
            "FC[1]": fc_1,
            "FC[2]": fc_2,
            "FC[5]": fc_5,
            "FC[6]": fc_6,
            "FC[7]": fc_7,
            "FC[8]": fc_8,
            "CA[45]": main_socket,
            "VX": vx,
            "MO_POST": mo_post,
            "SO_POST": so_post,
            "MF_POST": mf_post,
            "SR_POST": sr_post,
        }
    except (TypeError, ValueError, OverflowError) as exc:
        return _unknown(str(exc))

    effective_ac = min(ac, sd)
    effective_dc = min(dc, sd)
    position_delta = pu - px
    coordinate_status = (
        "ALIGNED" if position_delta == 0 else "DIVERGED / NEED-DATA")
    position_scale_numerator = fc_2 * fc_6 * fc_7
    position_scale_denominator = fc_1 * fc_5 * fc_8
    relation = (
        "AC[1]/DC LIMITED BY SD"
        if ac > sd or dc > sd
        else "AC[1]/DC WITHIN SD"
    )
    return PositionVelocitySnapshot(
        state=CURRENT,
        authority=CURRENT_DRIVE_READ_ONLY,
        evidence_label=EVIDENCE_LABEL,
        command_authority=COMMAND_LOCKED_NEED_DATA,
        reference_semantics=REFERENCE_SEMANTICS,
        motor_state=_motor_state(mo_post, so_post, mf_post, sr_post),
        mode_value=mode,
        mode_name=_MODE_NAMES[mode],
        absolute_target_count=pa,
        relative_target_count=pr,
        jog_velocity_count_per_s=jv,
        profile_speed_count_per_s=sp,
        acceleration_count_per_s2=ac,
        deceleration_count_per_s2=dc,
        stop_deceleration_count_per_s2=sd,
        effective_acceleration_count_per_s2=effective_ac,
        effective_deceleration_count_per_s2=effective_dc,
        feedback_position_count=px,
        eas_position_user_unit=pu,
        eas_to_raw_position_delta=position_delta,
        position_coordinate_status=coordinate_status,
        main_position_socket=main_socket,
        position_modulo_min=xm_min,
        position_modulo_max=xm_max,
        position_scale_numerator=position_scale_numerator,
        position_scale_denominator=position_scale_denominator,
        feedback_velocity_count_per_s=vx,
        limit_relation=relation,
        raw=MappingProxyType(normalized),
        sample_duration_s=duration,
        reason="",
    )


def read_position_velocity_snapshot(
        link: Any,
        *,
        clock_fn: Callable[[], float] = time.monotonic,
) -> PositionVelocitySnapshot:
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
                "drive session changed during position/velocity read")
        return decode_position_velocity_snapshot(
            raw, sample_duration_s=finished - started)
    except Exception as exc:
        return _unknown(str(exc))
