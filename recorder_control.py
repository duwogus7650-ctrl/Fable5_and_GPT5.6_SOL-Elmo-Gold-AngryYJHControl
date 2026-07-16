"""Pure validation and export helpers for the EAS-style Recorder UI.

The drive-facing .NET API is owned by :mod:`elmo_link`.  This module contains
no hardware I/O and deliberately supports only an Immediate, finite capture.
Advanced triggers, rollover and multi-drive synchronization remain explicit
NEED-DATA capabilities instead of being guessed from the EAS screenshot.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from typing import Any, Mapping, Sequence


RECORDER_BUFFER_SAMPLES = 16_384
MAX_SIGNALS = 16
WORKSPACE_SCHEMA = "angryyjh-recorder-workspace/v1"


class RecorderConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RecorderRequest:
    signals: tuple[str, ...]
    resolution_us: float = 200.0
    record_time_s: float = 1.0
    trigger: str = "immediate"


@dataclass(frozen=True)
class ResolvedRecorderRequest:
    signals: tuple[str, ...]
    requested_resolution_us: float
    actual_resolution_us: float
    time_resolution: int
    requested_record_time_s: float
    actual_record_time_s: float
    length_per_signal: int
    total_buffer_samples: int
    trigger: str = "immediate"


def _positive_finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecorderConfigError("%s must be a finite positive number" % name) from exc
    if not math.isfinite(number) or number <= 0:
        raise RecorderConfigError("%s must be a finite positive number" % name)
    return number


def validate_request(request: RecorderRequest) -> RecorderRequest:
    if not isinstance(request, RecorderRequest):
        raise RecorderConfigError("structured RecorderRequest is required")
    if request.trigger != "immediate":
        raise RecorderConfigError(
            "only Immediate trigger is implemented; Normal/Auto/Interval are NEED-DATA")
    cleaned = tuple(str(name).strip() for name in request.signals)
    if not cleaned or any(not name for name in cleaned):
        raise RecorderConfigError("select at least one non-empty recorder signal")
    if len(cleaned) > MAX_SIGNALS:
        raise RecorderConfigError("at most %d recorder signals are supported" % MAX_SIGNALS)
    if len(set(cleaned)) != len(cleaned):
        raise RecorderConfigError("recorder signal names must be unique")
    resolution = _positive_finite(request.resolution_us, "resolution_us")
    record_time = _positive_finite(request.record_time_s, "record_time_s")
    return RecorderRequest(cleaned, resolution, record_time, request.trigger)


def resolve_request(request: RecorderRequest, *, ts_us: float) -> ResolvedRecorderRequest:
    """Resolve EAS-like time fields to the integer .NET TimeResolution/length.

    The actual sample interval is surfaced rather than silently claiming the
    requested value.  Capacity is fail-closed at the documented 16K shared
    recorder buffer.
    """
    request = validate_request(request)
    base_us = _positive_finite(ts_us, "TS")
    ratio = request.resolution_us / base_us
    multiplier = max(1, int(round(ratio)))
    actual_us = multiplier * base_us
    # A request below TS or far from an integer multiplier cannot be represented
    # faithfully.  Half a TS is the nearest-integer quantization bound.
    if abs(actual_us - request.resolution_us) > base_us * 0.500001:
        raise RecorderConfigError(
            "requested resolution %.6g us cannot be represented from TS=%.6g us" %
            (request.resolution_us, base_us))
    length = max(1, int(round(request.record_time_s * 1e6 / actual_us)))
    per_signal_max = RECORDER_BUFFER_SAMPLES // len(request.signals)
    if length > per_signal_max:
        max_time = per_signal_max * actual_us * 1e-6
        raise RecorderConfigError(
            "recording exceeds shared 16K buffer: %d signals allow at most %d "
            "samples each (%.6g s at %.6g us)" %
            (len(request.signals), per_signal_max, max_time, actual_us))
    return ResolvedRecorderRequest(
        signals=request.signals,
        requested_resolution_us=request.resolution_us,
        actual_resolution_us=actual_us,
        time_resolution=multiplier,
        requested_record_time_s=request.record_time_s,
        actual_record_time_s=length * actual_us * 1e-6,
        length_per_signal=length,
        total_buffer_samples=length * len(request.signals),
        trigger=request.trigger,
    )


def workspace_payload(request: RecorderRequest) -> dict[str, Any]:
    checked = validate_request(request)
    return {"schema": WORKSPACE_SCHEMA, "request": asdict(checked)}


def parse_workspace(payload: Mapping[str, Any]) -> RecorderRequest:
    if not isinstance(payload, Mapping) or payload.get("schema") != WORKSPACE_SCHEMA:
        raise RecorderConfigError("unsupported recorder workspace schema")
    raw = payload.get("request")
    if not isinstance(raw, Mapping):
        raise RecorderConfigError("workspace request is missing")
    signals = raw.get("signals")
    if not isinstance(signals, (list, tuple)):
        raise RecorderConfigError("workspace signals must be a list")
    return validate_request(RecorderRequest(
        tuple(signals), raw.get("resolution_us"), raw.get("record_time_s"),
        raw.get("trigger", "immediate")))


def save_workspace(path: str, request: RecorderRequest) -> None:
    """Atomically save a local recorder setup.  This never talks to the drive."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp = target + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="") as handle:
        json.dump(workspace_payload(request), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp, target)


def load_workspace(path: str) -> RecorderRequest:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return parse_workspace(payload)


def validate_capture(
        data: Mapping[str, Any],
        resolved: ResolvedRecorderRequest) -> dict[str, Any]:
    """Validate a capture against the immutable request before COMPLETED."""
    if not isinstance(data, Mapping):
        raise RecorderConfigError("recording data must be a mapping")
    if not isinstance(resolved, ResolvedRecorderRequest):
        raise RecorderConfigError("resolved Recorder request is required")
    dt = _positive_finite(data.get("dt"), "recording dt")
    expected_dt = _positive_finite(
        resolved.actual_resolution_us, "actual_resolution_us") * 1e-6
    if not math.isclose(dt, expected_dt, rel_tol=1e-9, abs_tol=1e-12):
        raise RecorderConfigError(
            "recording dt %.12g disagrees with resolved dt %.12g" %
            (dt, expected_dt))
    for name in resolved.signals:
        if name not in data:
            raise RecorderConfigError("recording data missing signal %r" % name)
        try:
            values = list(data[name])
            finite = all(math.isfinite(float(value)) for value in values)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RecorderConfigError(
                "signal %r contains non-numeric samples" % name) from exc
        if len(values) != resolved.length_per_signal:
            raise RecorderConfigError(
                "signal %r has %d samples; expected exactly %d" %
                (name, len(values), resolved.length_per_signal))
        if not finite:
            raise RecorderConfigError("signal %r contains non-finite samples" % name)
    duration = resolved.length_per_signal * dt
    if not math.isclose(
            duration, resolved.actual_record_time_s,
            rel_tol=1e-9, abs_tol=1e-12):
        raise RecorderConfigError(
            "capture duration %.12g disagrees with resolved duration %.12g" %
            (duration, resolved.actual_record_time_s))
    return {
        "samples_per_signal": resolved.length_per_signal,
        "dt_s": dt,
        "actual_record_time_s": duration,
        "signals": list(resolved.signals),
    }


def export_csv(
        path: str,
        data: Mapping[str, Any],
        signals: Sequence[str],
        *,
        metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Export physical-double recorder arrays with a generated time column.

    Units are intentionally not invented.  Signal headers are the exact
    personality names and metadata records that units remain personality-owned.
    """
    names = tuple(str(name) for name in signals)
    if not names:
        raise RecorderConfigError("no signals selected for CSV export")
    dt = _positive_finite(data.get("dt"), "recording dt")
    arrays = []
    lengths = set()
    for name in names:
        if name not in data:
            raise RecorderConfigError("recording data missing signal %r" % name)
        values = list(data[name])
        if any(not math.isfinite(float(value)) for value in values):
            raise RecorderConfigError("signal %r contains non-finite samples" % name)
        arrays.append(values)
        lengths.add(len(values))
    if len(lengths) != 1:
        raise RecorderConfigError("recorder signal arrays have unequal lengths")
    count = lengths.pop()
    if count <= 0:
        raise RecorderConfigError("recorder signal arrays are empty")
    manifest = dict(metadata or {})
    expected_count = manifest.get("length_per_signal")
    if expected_count is not None and count != int(expected_count):
        raise RecorderConfigError(
            "CSV sample count %d disagrees with capture manifest %d" %
            (count, int(expected_count)))
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp = target + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_s", *names])
        for index in range(count):
            writer.writerow(["%.12g" % (index * dt),
                             *("%.17g" % float(values[index]) for values in arrays)])
    os.replace(temp, target)
    with open(target, "rb") as handle:
        csv_sha256 = hashlib.sha256(handle.read()).hexdigest()
    result = {
        "path": target,
        "samples_per_signal": count,
        "dt_s": dt,
        "signals": list(names),
        "units": "personality-owned; not inferred by exporter",
        "csv_sha256": csv_sha256,
    }
    sidecar = target + ".meta.json"
    sidecar_payload = {
        "schema": "angryyjh-recorder-capture-metadata/v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "csv_file": os.path.basename(target),
        **result,
        "capture_manifest": manifest,
    }
    sidecar_temp = sidecar + ".tmp"
    with open(sidecar_temp, "w", encoding="utf-8", newline="") as handle:
        json.dump(sidecar_payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    os.replace(sidecar_temp, sidecar)
    result["metadata_path"] = sidecar
    return result
