"""Bounded read-only digital-input snapshot for one Elmo Gold axis.

The reader queries only ``IL[1..6]``, ``IF[1..6]`` and one final ``IP`` value.
It never writes ``IB`` (which can clear sticky indications), sends any
assignment, changes an input mapping, enables the drive, or commands motion.
The decoded states are drive logical states, not physical pin-voltage
measurements and not safety evidence.
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
MAX_SNAPSHOT_DURATION_S = 2.0

EVIDENCE_LABEL = (
    "CURRENT DRIVE READ · IP + IL[1..6] + IF[1..6] · INPUTS 1..6 ONLY · "
    "DRIVE LOGICAL STATE · NOT PHYSICAL PIN VOLTAGE · "
    "NOT STO/E-STOP EVIDENCE"
)

FUNCTION_LABELS = (
    "Inhibit / freewheel",
    "Hardware + auxiliary stop",
    "Ignore",
    "General purpose",
    "Reverse limit (RLS)",
    "Forward limit (FLS)",
    "Begin motion (BG)",
    "Soft stop (ST)",
    "Main home",
    "Auxiliary home",
    "Hardware + software stop",
    "Abort / freewheel",
    "Reserved safety-compatibility code",
    "Additional abort / freewheel",
    "Engage follower / ECAM",
    "Disengage follower / ECAM",
)

_IL_ALLOWED_MASK = 0x11F
_UINT32_MAX = (1 << 32) - 1
_COMMANDS = (
    *(f"IL[{index}]" for index in range(1, 7)),
    *(f"IF[{index}]" for index in range(1, 7)),
    "IP",
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DigitalInputRow:
    number: int
    active: bool
    state_label: str
    function_code: int
    function_label: str
    polarity: str
    sticky: bool
    filter_ms: float
    il_raw: int


@dataclass(frozen=True, slots=True)
class DigitalInputSnapshot:
    state: str
    authority: str
    evidence_label: str
    inputs: tuple[DigitalInputRow, ...]
    raw: Mapping[str, int | float]
    sample_duration_s: Optional[float]
    reason: str


_EAS_ROOT = (
    r"C:\Program Files\Elmo Motion Control\Elmo Application Studio III"
    r"\NetHelp\Content"
)
_COMMAND_ROOT = _EAS_ROOT + r"\Gold Line Command Reference"
SOURCES = (
    DocumentSource(
        "single_axis_help",
        _EAS_ROOT
        + r"\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities.htm",
        "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE",
    ),
    DocumentSource(
        "ip",
        _COMMAND_ROOT + r"\IP Input Port.htm",
        "0594BD5A9A1B8DCC0128985747E0ED86861A917A87CB292528180B186A413336",
    ),
    DocumentSource(
        "il",
        _COMMAND_ROOT + r"\IL Digital Input Logic.htm",
        "F5C058B8A2CE435411A8114D7BB30ADD4E640D5BBA8B14737702096BF60F99C2",
    ),
    DocumentSource(
        "if",
        _COMMAND_ROOT + r"\IF Digital Input Filter.htm",
        "1803C3A188B45B4E0945D161211FDD04887B12727F209977C52871F4292260BA",
    ),
)


def _unknown(reason: str) -> DigitalInputSnapshot:
    return DigitalInputSnapshot(
        state=UNKNOWN,
        authority=AUTHORITY_UNKNOWN,
        evidence_label=EVIDENCE_LABEL,
        inputs=(),
        raw=MappingProxyType({}),
        sample_duration_s=None,
        reason=str(reason or "digital-input snapshot unavailable"),
    )


def _decimal(value: object, key: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("%s must be a finite number, not %r" % (key, value))
    try:
        result = Decimal(str(value).strip().rstrip(";").strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(
            "%s must be a finite number, not %r" % (key, value)) from exc
    if not result.is_finite():
        raise ValueError("%s must be finite, not %r" % (key, value))
    return result


def _integer(
        raw: Mapping[str, object],
        key: str,
        *,
        minimum: int,
        maximum: int,
) -> int:
    if key not in raw:
        raise ValueError("%s is missing" % key)
    numeric = _decimal(raw[key], key)
    if numeric != numeric.to_integral_value():
        raise ValueError("%s must be an integer, not %r" % (key, raw[key]))
    result = int(numeric)
    if result < minimum or result > maximum:
        raise ValueError(
            "%s=%s is outside %s..%s" %
            (key, result, minimum, maximum))
    return result


def _filter_ms(raw: Mapping[str, object], key: str) -> float:
    if key not in raw:
        raise ValueError("%s is missing" % key)
    numeric = float(_decimal(raw[key], key))
    if not 0.0 <= numeric <= 500.0:
        raise ValueError("%s=%s is outside 0.0..500.0 ms" % (key, numeric))
    return numeric


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


def decode_digital_input_snapshot(
        raw: Mapping[str, object] | None,
        *,
        sample_duration_s: object,
) -> DigitalInputSnapshot:
    """Decode one exact IP/IL/IF read set without performing drive I/O."""
    if not isinstance(raw, Mapping):
        return _unknown("raw digital-input mapping is missing")
    try:
        duration = _duration(sample_duration_s)
        ip = _integer(raw, "IP", minimum=0, maximum=_UINT32_MAX)
        normalized: dict[str, int | float] = {"IP": ip}
        rows: list[DigitalInputRow] = []
        for number in range(1, 7):
            il_key = "IL[%d]" % number
            if_key = "IF[%d]" % number
            il_value = _integer(
                raw, il_key, minimum=0, maximum=0xFFFF)
            reserved = il_value & ~_IL_ALLOWED_MASK
            if reserved:
                raise ValueError(
                    "%s has reserved bits set: 0x%X" %
                    (il_key, reserved))
            function_code = (il_value >> 1) & 0xF
            filter_ms = _filter_ms(raw, if_key)
            active = bool(ip & (1 << (15 + number)))
            normalized[il_key] = il_value
            normalized[if_key] = filter_ms
            rows.append(DigitalInputRow(
                number=number,
                active=active,
                state_label=(
                    "ACTIVE · DRIVE LOGICAL"
                    if active else "INACTIVE · DRIVE LOGICAL"
                ),
                function_code=function_code,
                function_label=FUNCTION_LABELS[function_code],
                polarity=(
                    "ACTIVE_HIGH" if il_value & 0x1 else "ACTIVE_LOW"
                ),
                sticky=bool(il_value & (1 << 8)),
                filter_ms=filter_ms,
                il_raw=il_value,
            ))
    except (TypeError, ValueError, OverflowError) as exc:
        return _unknown(str(exc))

    return DigitalInputSnapshot(
        state=CURRENT,
        authority=CURRENT_DRIVE_READ_ONLY,
        evidence_label=EVIDENCE_LABEL,
        inputs=tuple(rows),
        raw=MappingProxyType(normalized),
        sample_duration_s=duration,
        reason="",
    )


def read_digital_input_snapshot(
        link: Any,
        *,
        clock_fn: Callable[[], float] = time.monotonic,
) -> DigitalInputSnapshot:
    """Read the exact bounded query set and bind it to one link session."""
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
        for command in _COMMANDS:
            try:
                raw[command] = link.command(
                    command, timeout_ms=READ_TIMEOUT_MS)
            except Exception as exc:
                raise RuntimeError(
                    "%s read failed: %s" % (command, exc)) from exc
        finished = float(clock_fn())
        if not math.isfinite(finished):
            raise ValueError("sample finish clock is not finite")
        if get_session() is not session:
            raise RuntimeError("drive session changed during digital-input read")
        return decode_digital_input_snapshot(
            raw, sample_duration_s=finished - started)
    except Exception as exc:
        return _unknown(str(exc))
