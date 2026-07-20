"""Local-only model for the five Current presets observed in EAS III.

EAS exposes five editable host presets named Current Command 1..5. Each Set
control targets the same drive command, TC. This module only validates and
describes local draft values; it performs no drive I/O and grants no authority
to enable the motor or assign TC.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Optional


PRESET_COUNT = 5
COMMAND_REGISTER = "TC"
OUTPUT_LOCKED_NEED_DATA = "OUTPUT LOCKED / NEED-DATA"
EAS_DEFAULT_CURRENT_A = 0.0
EAS_OBSERVED_CONTRACT = (
    "2026-07-19 EAS III LIVE UI OBSERVED: FIVE HOST PRESETS, EACH SET "
    "CONTROL TARGETS THE SAME TC REGISTER; DEFAULT 0 A; SET DISABLED WHILE "
    "MOTOR DISABLED. LOCAL DRAFT ONLY / NO DRIVE I/O / OUTPUT LOCKED / "
    "NEED-DATA."
)


@dataclass(frozen=True, slots=True)
class CurrentCommandPreset:
    index: int
    value_a: float
    command_register: str
    command_preview: str
    status: str
    output_locked: bool


def _finite_number(name: str, value: object, *, positive: bool) -> float:
    if isinstance(value, bool):
        raise ValueError("%s must be a finite number" % name)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be a finite number" % name) from exc
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise ValueError(
            "%s must be a %sfinite number" %
            (name, "positive " if positive else ""))
    return number


def _optional_limit(name: str, value: object) -> Optional[float]:
    if value is None:
        return None
    return _finite_number(name, value, positive=True)


def _format_tc(value_a: float) -> str:
    if value_a == 0.0:
        return "TC=0"
    return "TC=%s" % format(value_a, ".12g")


def build_current_command_presets(
        values_a: Iterable[object],
        *,
        continuous_limit_a: object = None,
        peak_limit_a: object = None,
        maximum_drive_current_a: object = None,
) -> tuple[CurrentCommandPreset, ...]:
    """Validate exactly five local drafts and classify observed-limit bands."""
    values = tuple(values_a)
    if len(values) != PRESET_COUNT:
        raise ValueError(
            "exactly %d Current preset values are required" % PRESET_COUNT)
    normalized = tuple(
        _finite_number(
            "Current Command %d" % index,
            value,
            positive=False,
        )
        for index, value in enumerate(values, start=1)
    )
    continuous = _optional_limit(
        "continuous_limit_a", continuous_limit_a)
    peak = _optional_limit("peak_limit_a", peak_limit_a)
    maximum = _optional_limit(
        "maximum_drive_current_a", maximum_drive_current_a)
    if continuous is not None and peak is not None and continuous > peak:
        raise ValueError("continuous_limit_a exceeds peak_limit_a")
    if peak is not None and maximum is not None and peak > maximum:
        raise ValueError("peak_limit_a exceeds maximum_drive_current_a")
    if continuous is not None and maximum is not None and continuous > maximum:
        raise ValueError(
            "continuous_limit_a exceeds maximum_drive_current_a")

    result = []
    for index, value in enumerate(normalized, start=1):
        magnitude = abs(value)
        if maximum is not None and magnitude > maximum:
            status = "INVALID / ABOVE DRIVE MAXIMUM"
        elif peak is not None and magnitude > peak:
            status = "WARNING / ABOVE PEAK LIMIT"
        elif continuous is not None and magnitude > continuous:
            status = "WARNING / ABOVE CONTINUOUS LIMIT"
        elif any(
                limit is not None
                for limit in (continuous, peak, maximum)):
            status = "LOCAL DRAFT / WITHIN OBSERVED LIMITS"
        else:
            status = "LOCAL DRAFT / LIMITS UNKNOWN"
        result.append(CurrentCommandPreset(
            index=index,
            value_a=value,
            command_register=COMMAND_REGISTER,
            command_preview=_format_tc(value),
            status=status,
            output_locked=True,
        ))
    return tuple(result)
