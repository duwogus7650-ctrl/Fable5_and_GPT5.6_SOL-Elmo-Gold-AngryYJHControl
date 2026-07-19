"""Bounded read-only digital-output snapshot for one Gold Twitter axis.

The reader queries only ``OL[1..4]``, ``GO[1..4]`` and one final ``OP``
value.  It never sends an assignment, changes output routing or function,
toggles an output, enables the drive, or commands motion.  The decoded state
is drive-reported logical activation/configuration, not a physical pin
voltage/current measurement and not safety or STO test evidence.
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
    "CURRENT DRIVE READ · OP + OL[1..4] + GO[1..4] · OUTPUTS 1..4 ONLY · "
    "DRIVE LOGICAL ACTIVATION / CONFIGURATION · NOT PHYSICAL PIN "
    "VOLTAGE/CURRENT · NOT STO TEST EVIDENCE"
)

FUNCTION_LABELS = (
    "General purpose",
    "Amplifier OK (AOK)",
    "Brake",
    "Servo state (MO)",
    "Motor fault (MF)",
    "Target reached (MS)",
)

ROUTE_LABELS = MappingProxyType({
    0: "Function via OL[N]",
    1: "Port B output compare",
    2: "Port A output compare",
    7: "STO status indication · NOT STO TEST",
})

DOCUMENT_CONFLICTS = (
    "OL_RANGE_CONFLICT: the installed Gold command page attributes state "
    "OL[N] range 0..9, while its bit-field/possible-values content defines "
    "Target Reached values 10 and 11; this reader accepts only the explicitly "
    "documented union 0..11 and performs no write.",
)

_UINT32_MAX = (1 << 32) - 1
_COMMANDS = (
    *(f"OL[{index}]" for index in range(1, 5)),
    *(f"GO[{index}]" for index in range(1, 5)),
    "OP",
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DigitalOutputRow:
    number: int
    logic_voltage: str
    active: bool
    state_label: str
    function_code: int
    function_label: str
    polarity: str
    route_code: int
    route_label: str
    physical_level: str
    ol_raw: int
    go_raw: int


@dataclass(frozen=True, slots=True)
class DigitalOutputSnapshot:
    state: str
    authority: str
    evidence_label: str
    outputs: tuple[DigitalOutputRow, ...]
    raw: Mapping[str, int]
    sample_duration_s: Optional[float]
    reason: str


_EAS_ROOT = (
    r"C:\Program Files\Elmo Motion Control\Elmo Application Studio III"
    r"\NetHelp\Content"
)
_COMMAND_ROOT = _EAS_ROOT + r"\Gold Line Command Reference"
SOURCES = (
    DocumentSource(
        "op",
        _COMMAND_ROOT + r"\OP Output Port.htm",
        "BFDE83C2EC00D1FCD3F2A8ADA8CCF7288836DE0E510431591E8A7078EF61FDF6",
    ),
    DocumentSource(
        "go",
        _COMMAND_ROOT + r"\GO Digital Output Source.htm",
        "4D4E7CBCE1EADBA8ED820224B441AFC370D5E264676A4AD22CC399361CE247BE",
    ),
    DocumentSource(
        "ol",
        _COMMAND_ROOT + r"\OL Output Logic.htm",
        "F6A33CF4609B61AA31EB36F3B811387537A8208B495ACCA81CFB9A7B93331291",
    ),
    DocumentSource(
        "gold_twitter_installation_guide",
        r"C:\Users\user\OneDrive\바탕 화면\Elmo\MAN-G-TWIIG_s.pdf",
        "F8AE035E8A1E621BEA7679B4B042551AB7F23AC203E3D59AA681ABC53A2E64F7",
    ),
)


def _unknown(reason: str) -> DigitalOutputSnapshot:
    return DigitalOutputSnapshot(
        state=UNKNOWN,
        authority=AUTHORITY_UNKNOWN,
        evidence_label=EVIDENCE_LABEL,
        outputs=(),
        raw=MappingProxyType({}),
        sample_duration_s=None,
        reason=str(reason or "digital-output snapshot unavailable"),
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


def decode_digital_output_snapshot(
        raw: Mapping[str, object] | None,
        *,
        sample_duration_s: object,
) -> DigitalOutputSnapshot:
    """Decode one exact OP/OL/GO read set without performing drive I/O."""
    if not isinstance(raw, Mapping):
        return _unknown("raw digital-output mapping is missing")
    try:
        duration = _duration(sample_duration_s)
        op = _integer(raw, "OP", minimum=0, maximum=_UINT32_MAX)
        normalized: dict[str, int] = {"OP": op}
        rows: list[DigitalOutputRow] = []
        for number in range(1, 5):
            ol_key = "OL[%d]" % number
            go_key = "GO[%d]" % number
            ol_value = _integer(raw, ol_key, minimum=0, maximum=11)
            go_value = _integer(raw, go_key, minimum=0, maximum=7)
            if go_value not in ROUTE_LABELS:
                raise ValueError(
                    "%s=%s is not one of 0, 1, 2, 7" %
                    (go_key, go_value))
            function_code = ol_value >> 1
            active = bool(op & (1 << (number - 1)))
            normalized[ol_key] = ol_value
            normalized[go_key] = go_value
            rows.append(DigitalOutputRow(
                number=number,
                logic_voltage="5 V logic" if number <= 2 else "3.3 V logic",
                active=active,
                state_label=(
                    "ACTIVE · DRIVE LOGICAL ACTIVATION"
                    if active
                    else "INACTIVE · DRIVE LOGICAL ACTIVATION"
                ),
                function_code=function_code,
                function_label=FUNCTION_LABELS[function_code],
                polarity=(
                    "ACTIVE_HIGH" if ol_value & 0x1 else "ACTIVE_LOW"
                ),
                route_code=go_value,
                route_label=ROUTE_LABELS[go_value],
                physical_level="UNVERIFIED",
                ol_raw=ol_value,
                go_raw=go_value,
            ))
    except (TypeError, ValueError, OverflowError) as exc:
        return _unknown(str(exc))

    return DigitalOutputSnapshot(
        state=CURRENT,
        authority=CURRENT_DRIVE_READ_ONLY,
        evidence_label=EVIDENCE_LABEL,
        outputs=tuple(rows),
        raw=MappingProxyType(normalized),
        sample_duration_s=duration,
        reason="",
    )


def read_digital_output_snapshot(
        link: Any,
        *,
        clock_fn: Callable[[], float] = time.monotonic,
) -> DigitalOutputSnapshot:
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
            raise RuntimeError(
                "drive session changed during digital-output read")
        return decode_digital_output_snapshot(
            raw, sample_duration_s=finished - started)
    except Exception as exc:
        return _unknown(str(exc))
